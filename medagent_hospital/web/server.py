"""Stdlib demo server for the MedAgent-Hospital dashboard.

Runs the pixel-hospital simulation UI and the evolution analysis views.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from medagent_hospital.agents.doctor import DoctorAgent
from medagent_hospital.agents.guide import GuideAgent
from medagent_hospital.agents.nurse import NurseAgent
from medagent_hospital.agents.patient import PatientAgent
from medagent_hospital.agents.registry import DoctorRegistry
from medagent_hospital.knowledge import load_knowledge_base
from medagent_hospital.memory.case_base import MedicalCaseBase
from medagent_hospital.memory.experience_base import ExperienceBase
from medagent_hospital.simulacrum.evolution import (
    EvolutionConfig,
    EvolutionTrainer,
    apply_variant,
)
from medagent_hospital.simulacrum.patient_generator import PatientGenerator
from medagent_hospital.simulacrum.runtime import HospitalRuntime
from medagent_hospital.simulacrum.models import (
    ConsultationContext,
    HospitalState,
    PatientRecord,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


class DemoState:
    def __init__(self) -> None:
        self.kb = load_knowledge_base()
        self.latest_evolution: dict | None = None
        self.evolved_registry = None
        self.guide_case_base = MedicalCaseBase()
        self.guide_experience_base = ExperienceBase()
        self.assistant_sessions: dict[str, "AssistantSession"] = {}
        self.lock = threading.Lock()


STATE = DemoState()


def _json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8")) if raw else {}


def _kb_overview() -> dict:
    kb = STATE.kb
    departments = []
    for department in kb.departments:
        diseases = kb.by_department(department)
        departments.append(
            {
                "name": department,
                "disease_count": len(diseases),
                "diseases": [
                    {
                        "id": disease.id,
                        "name": disease.name,
                        "symptom_count": len(disease.symptoms),
                    }
                    for disease in diseases
                ],
            }
        )
    return {"departments": departments, "total_diseases": len(kb.diseases)}


def _run_episode(body: dict) -> dict:
    seed = body.get("seed")
    generator = PatientGenerator(
        STATE.kb,
        seed=seed if isinstance(seed, int) else random.randint(0, 2**31 - 1),
        distractor_probability=0.25,
    )
    patient = generator.generate(
        department=body.get("department") or None,
        disease_id=body.get("disease_id") or None,
    )

    use_memory = bool(body.get("use_memory", False))
    with STATE.lock:
        registry = STATE.evolved_registry
    reasoner = str(body.get("reasoner", "rule")).lower()
    force_consultation = bool(body.get("force_consultation", False))
    guide = GuideAgent(
        kb=STATE.kb,
        reasoner=reasoner,
        case_base=STATE.guide_case_base,
        experience_base=STATE.guide_experience_base,
    )
    doctor_registry = DoctorRegistry(
        STATE.kb, reasoner=reasoner, doctors_per_department=3
    )
    if use_memory and registry:
        for department in STATE.kb.departments:
            source = registry.get(department, 0)
            target = doctor_registry.get(department, 0)
            target.case_base = source.case_base
            target.experience_base = source.experience_base

    runtime = HospitalRuntime(
        patient_agent=PatientAgent(),
        nurse_agent=NurseAgent(kb=STATE.kb),
        guide_agent=guide,
        doctor_agent=doctor_registry,
        nurse_questions=2,
        consultation=True,
        consultation_threshold=1_000_000.0 if force_consultation else 0.6,
        max_consultants=2,
    )
    context = runtime.run_episode(patient)
    guide_update = guide.update_memory(context, patient)
    return {
        "patient": {
            "id": patient.patient_id,
            "name": patient.name,
            "gender": patient.gender,
            "age": patient.age,
            "symptoms": patient.symptoms,
            "medical_history": patient.medical_history,
        },
        "ground_truth": {
            "disease_id": patient.ground_truth_disease_id,
            "disease_name": patient.ground_truth_disease_name,
        },
        "department": context.department,
        "triage_reason": context.triage_reason,
        "ordered_exams": context.ordered_exams,
        "exam_results": [
            {"name": exam.name, "findings": exam.findings}
            for exam in context.exam_results
        ],
        "diagnosis": {
            "disease_id": context.diagnosis_id,
            "disease_name": context.diagnosis_name,
            "reasoning": context.diagnosis_reasoning,
            "scores": context.scores,
        },
        "treatment": context.treatment,
        "retrieved_cases": context.retrieved_cases,
        "retrieved_rules": context.retrieved_rules,
        "correct": context.diagnosis_id == patient.ground_truth_disease_id,
        "memory_used": use_memory and registry is not None,
        "reasoner": reasoner,
        "guide": {
            "cases": len(guide.case_base),
            "rules": len(guide.experience_base),
            "last_update": guide_update,
        },
        "nurse_questions": context.nurse_questions,
        "consultation_triggered": context.consultation_triggered,
        "opinions": context.opinions,
        "lead_diagnosis": {
            "disease_id": context.lead_diagnosis_id,
            "disease_name": context.lead_diagnosis_name,
            "reasoning": context.lead_diagnosis_reasoning,
        },
        "transcript": context.transcript,
    }


def _run_evolution(body: dict) -> dict:
    config = EvolutionConfig(
        patients_per_department=int(body.get("patients_per_department", 60)),
        test_patients_per_department=int(body.get("test_patients_per_department", 20)),
        validation_patients_per_disease=1,
        batch_size=int(body.get("batch_size", 20)),
        seed=int(body.get("seed", 42)),
    )
    variants = tuple(body.get("variants", ["A", "B", "C", "D"]))
    results: dict[str, dict] = {}
    evolved_registry = None
    for variant in variants:
        trainer = EvolutionTrainer(STATE.kb, apply_variant(config, variant))
        report, doctors = trainer.train(variant, return_doctors=True)
        results[variant] = report
        if variant == "D":
            evolved_registry = doctors
    with STATE.lock:
        STATE.latest_evolution = results
        STATE.evolved_registry = evolved_registry
    return results


@dataclass
class AssistantSession:
    session_id: str
    patient: PatientRecord
    stage: str = "guide"
    department: str | None = None
    decisions: dict = field(default_factory=dict)
    messages: list[dict] = field(default_factory=list)
    pending_questions: list[str] = field(default_factory=list)
    question_index: int = 0
    suggestion: dict | None = None
    created_at: float = field(default_factory=time.time)


def _parse_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [
            item.strip()
            for item in value.replace("，", ",").split(",")
            if item.strip()
        ]
    return []


def _assistant_patient(body: dict) -> PatientRecord:
    gender = str(body.get("gender", "any")).strip().lower()
    if gender not in {"male", "female", "any"}:
        gender = "any"
    try:
        age = int(body.get("age", 40))
    except (TypeError, ValueError):
        age = 40
    return PatientRecord(
        patient_id=f"AST-{uuid.uuid4().hex[:8].upper()}",
        name=str(body.get("name", "辅助诊断病人")).strip() or "辅助诊断病人",
        gender=gender,
        age=max(0, min(120, age)),
        symptoms=_parse_list(body.get("symptoms")),
        medical_history=_parse_list(body.get("medical_history")),
        risk_factors=_parse_list(body.get("risk_factors")),
        exam_results=[],
        ground_truth_disease_id="",
        ground_truth_disease_name="",
    )


def _triage_suggestion(patient: PatientRecord) -> dict:
    guide = GuideAgent(kb=STATE.kb, reasoner="rule")
    department, matched = guide._rule_triage(patient)
    department_scores = []
    for candidate in STATE.kb.departments:
        symptoms: set[str] = set()
        for disease in STATE.kb.by_department(candidate):
            symptoms.update(disease.symptoms)
        department_scores.append(
            {
                "department": candidate,
                "matched": len(set(patient.symptoms) & symptoms),
            }
        )
    department_scores.sort(key=lambda item: item["matched"], reverse=True)
    return {
        "department": department,
        "reason": f"症状匹配 {matched}",
        "departments": department_scores,
    }


def _nurse_questions(
    patient: PatientRecord, department: str, limit: int = 3
) -> list[str]:
    doctor = DoctorAgent(kb=STATE.kb, reasoner="rule")
    context = ConsultationContext(patient=patient)
    context.department = department
    context.current_state = HospitalState.SYMPTOM_QUESTION
    questions: list[str] = []
    for _ in range(limit):
        action = doctor._ask_symptom(context)
        if action.type != "ask_symptom":
            break
        symptom = action.payload.get("symptom", "")
        if not symptom or symptom in questions:
            break
        questions.append(symptom)
        context.asked_symptoms.append(symptom)
    return questions


def _doctor_suggestion(patient: PatientRecord, department: str) -> dict:
    doctor = DoctorAgent(
        kb=STATE.kb,
        reasoner="rule",
        case_base=STATE.guide_case_base,
        experience_base=STATE.guide_experience_base,
    )
    context = ConsultationContext(patient=patient)
    context.department = department
    context.current_state = HospitalState.DIAGNOSIS
    scored = doctor._rank_candidates(context)
    candidates = [
        {
            "disease_id": disease.id,
            "disease_name": disease.name,
            "department": disease.department,
            "score": round(score, 3),
        }
        for score, disease in scored[:5]
    ]
    exams: list[str] = []
    for _, disease in scored[:2]:
        for exam in disease.examinations:
            if exam.name not in exams:
                exams.append(exam.name)
    best = scored[0][1] if scored else None
    return {
        "candidates": candidates,
        "best_id": best.id if best else "",
        "best_name": best.name if best else "",
        "exams": exams[:6],
        "treatment": list(best.treatments) if best else [],
        "reasoning": doctor._build_reasoning(context, scored) if scored else "无法识别",
        "retrieved_cases": context.retrieved_cases,
        "retrieved_rules": context.retrieved_rules,
    }


def _chief_suggestion(session: AssistantSession) -> dict:
    doctor_decision = session.decisions.get("doctor", {})
    disease = STATE.kb.get(doctor_decision.get("disease_id", "")) or STATE.kb.by_name(
        doctor_decision.get("disease_name", "")
    )
    nurse_answers = session.decisions.get("nurse", {}).get("answered", [])
    return {
        "department": session.department,
        "diagnosis_id": doctor_decision.get("disease_id", ""),
        "diagnosis_name": doctor_decision.get("disease_name", ""),
        "treatment": list(disease.treatments) if disease else [],
        "follow_up": ["按医嘱复查", "症状加重或新发症状及时复诊"],
        "summary": (
            f"导医分诊至{session.department or '待定'}；护士追问 {len(nurse_answers)} 项；"
            f"主诊建议 {doctor_decision.get('disease_name', '待定')}。"
        ),
    }


def _assistant_state(session: AssistantSession) -> dict:
    return {
        "session_id": session.session_id,
        "stage": session.stage,
        "done": session.stage == "done",
        "patient": {
            "id": session.patient.patient_id,
            "name": session.patient.name,
            "gender": session.patient.gender,
            "age": session.patient.age,
            "symptoms": list(session.patient.symptoms),
            "medical_history": list(session.patient.medical_history),
            "risk_factors": list(session.patient.risk_factors),
        },
        "department": session.department,
        "decisions": session.decisions,
        "messages": session.messages,
        "pending_questions": list(session.pending_questions),
        "question_index": session.question_index,
        "suggestion": session.suggestion,
    }


def _get_assistant_session(body: dict) -> AssistantSession:
    session = STATE.assistant_sessions.get(str(body.get("session_id", "")))
    if session is None:
        raise ValueError("会话不存在")
    return session


def _start_assistant(body: dict) -> dict:
    patient = _assistant_patient(body)
    if not patient.symptoms:
        raise ValueError("请至少输入一个症状")
    session = AssistantSession(
        session_id=uuid.uuid4().hex[:12],
        patient=patient,
    )
    suggestion = _triage_suggestion(patient)
    session.suggestion = suggestion
    session.messages.append(
        {
            "role": "guide",
            "stage": "guide",
            "content": f"根据当前症状，建议先前往「{suggestion['department']}」就诊。",
            "payload": suggestion,
        }
    )
    with STATE.lock:
        STATE.assistant_sessions[session.session_id] = session
    return _assistant_state(session)


def _advance_to_doctor(session: AssistantSession) -> dict:
    suggestion = _doctor_suggestion(session.patient, session.department)
    session.suggestion = suggestion
    session.stage = "doctor"
    session.messages.append(
        {
            "role": "doctor",
            "stage": "doctor",
            "content": "主诊医师建议：请结合检查与病史复核以下鉴别诊断。",
            "payload": suggestion,
        }
    )
    return _assistant_state(session)


def _answer_assistant(body: dict) -> dict:
    session = _get_assistant_session(body)
    if session.stage != "nurse":
        raise ValueError(f"当前阶段为 {session.stage}，不能回答追问")
    symptom = str(body.get("symptom", "")).strip()
    present = bool(body.get("present", False))
    if not symptom:
        raise ValueError("缺少症状字段")
    if present and symptom not in session.patient.symptoms:
        session.patient.symptoms.append(symptom)
    answered = session.decisions.setdefault("nurse", {}).setdefault("answered", [])
    answered.append({"symptom": symptom, "present": present})
    session.messages.append(
        {
            "role": "user",
            "stage": "nurse",
            "content": f"{'有' if present else '没有'} {symptom}",
            "payload": {"symptom": symptom, "present": present},
        }
    )
    session.question_index += 1
    if session.question_index < len(session.pending_questions):
        question = session.pending_questions[session.question_index]
        session.suggestion = {
            "question": question,
            "question_index": session.question_index + 1,
            "total": len(session.pending_questions),
        }
        session.messages.append(
            {
                "role": "nurse",
                "stage": "nurse",
                "content": f"请确认：{question}？",
                "payload": session.suggestion,
            }
        )
        return _assistant_state(session)
    session.messages.append(
        {"role": "nurse", "stage": "nurse", "content": "护士确认：问诊完成", "payload": {}}
    )
    return _advance_to_doctor(session)


def _confirm_assistant(body: dict) -> dict:
    session = _get_assistant_session(body)
    stage = str(body.get("stage", ""))
    accepted = bool(body.get("accepted", True))
    override = str(body.get("override", "")).strip()
    if stage != session.stage:
        raise ValueError(f"当前阶段为 {session.stage}，不能确认 {stage}")

    if stage == "guide":
        department = override or (session.suggestion or {}).get("department", "")
        if department not in STATE.kb.departments:
            raise ValueError(f"无效科室: {department}")
        session.department = department
        session.decisions["guide"] = {
            "department": department,
            "accepted": accepted,
            "override": override,
        }
        session.messages.append(
            {
                "role": "user",
                "stage": "guide",
                "content": f"导医确认：{department}",
                "payload": {},
            }
        )
        questions = _nurse_questions(session.patient, department)
        session.pending_questions = questions
        session.question_index = 0
        session.stage = "nurse"
        if not questions:
            return _advance_to_doctor(session)
        first = questions[0]
        session.suggestion = {
            "question": first,
            "question_index": 1,
            "total": len(questions),
        }
        session.messages.append(
            {
                "role": "nurse",
                "stage": "nurse",
                "content": f"为了完善评估，请确认：{first}？",
                "payload": session.suggestion,
            }
        )
        return _assistant_state(session)

    if stage == "nurse":
        session.messages.append(
            {"role": "user", "stage": "nurse", "content": "护士确认：完成问诊", "payload": {}}
        )
        return _advance_to_doctor(session)

    if stage == "doctor":
        suggestion = session.suggestion or {}
        disease_id = override or suggestion.get("best_id", "")
        disease = STATE.kb.get(disease_id)
        if disease is None:
            disease = STATE.kb.by_name(override or suggestion.get("best_name", ""))
        if disease is None:
            raise ValueError("未选择有效诊断")
        session.decisions["doctor"] = {
            "disease_id": disease.id,
            "disease_name": disease.name,
            "accepted": accepted,
            "override": override,
            "reasoning": suggestion.get("reasoning", ""),
        }
        session.messages.append(
            {
                "role": "user",
                "stage": "doctor",
                "content": f"主诊确认：{disease.name}",
                "payload": {"disease_id": disease.id, "disease_name": disease.name},
            }
        )
        chief = _chief_suggestion(session)
        session.suggestion = chief
        session.stage = "chief"
        session.messages.append(
            {
                "role": "chief",
                "stage": "chief",
                "content": "主任医师汇总：请复核最终诊断、治疗与随访建议。",
                "payload": chief,
            }
        )
        return _assistant_state(session)

    if stage == "chief":
        decision = session.decisions.get("doctor", {})
        session.decisions["chief"] = {"accepted": accepted, "override": override}
        session.stage = "done"
        session.suggestion = None
        session.messages.append(
            {
                "role": "chief",
                "stage": "chief",
                "content": f"已确认最终方案：{decision.get('disease_name', '')}。辅助诊断完成。",
                "payload": {"done": True},
            }
        )
        return _assistant_state(session)

    raise ValueError(f"未知阶段: {stage}")


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "MedAgentHospital/0.1"

    def log_message(self, fmt: str, *args) -> None:  # keep console quiet
        return

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            _json_response(self, {"status": "ok", "model": "rule"})
            return
        if path == "/api/kb/overview":
            _json_response(self, _kb_overview())
            return
        if path == "/api/evolution/latest":
            with STATE.lock:
                _json_response(self, {"results": STATE.latest_evolution or {}})
            return
        if path == "/api/assistant/state":
            session_id = parse_qs(urlparse(self.path).query).get("session_id", [""])[0]
            session = STATE.assistant_sessions.get(session_id)
            if session is None:
                _json_response(self, {"error": "会话不存在"}, status=404)
                return
            _json_response(self, _assistant_state(session))
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        body = _read_json(self)
        try:
            if path == "/api/episode/run":
                _json_response(self, _run_episode(body))
                return
            if path == "/api/evolution/run":
                _json_response(self, _run_evolution(body))
                return
            if path == "/api/assistant/start":
                _json_response(self, _start_assistant(body))
                return
            if path == "/api/assistant/confirm":
                _json_response(self, _confirm_assistant(body))
                return
            if path == "/api/assistant/answer":
                _json_response(self, _answer_assistant(body))
                return
        except ValueError as exc:
            _json_response(self, {"error": str(exc)}, status=400)
            return
        except Exception as exc:  # pragma: no cover - defensive API boundary
            _json_response(self, {"error": str(exc)}, status=500)
            return
        _json_response(self, {"error": "not found"}, status=404)

    def _serve_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        elif path in ("/assistant", "/assistant/"):
            path = "/assistant.html"
        relative = path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            _json_response(self, {"error": "not found"}, status=404)
            return
        content_type = "text/html; charset=utf-8"
        if target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif target.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif target.suffix == ".svg":
            content_type = "image/svg+xml"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), DemoHandler)
    print(f"MedAgent-Hospital dashboard: http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
