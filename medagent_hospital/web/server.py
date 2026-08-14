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
from medagent_hospital.web.hospital_store import HospitalRecordStore

STATIC_DIR = Path(__file__).resolve().parent / "static"
AUDIO_DIR = Path(__file__).resolve().parents[2] / "data" / "generated" / "audio"


class DemoState:
    def __init__(self) -> None:
        self.kb = load_knowledge_base()
        self.latest_evolution: dict | None = None
        self.evolved_registry = None
        self.guide_case_base = MedicalCaseBase()
        self.guide_experience_base = ExperienceBase()
        self.assistant_sessions: dict[str, "AssistantSession"] = {}
        self.hospital_store = HospitalRecordStore()
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
    reasoner: str = "rule"
    stage: str = "guide"
    department: str | None = None
    decisions: dict = field(default_factory=dict)
    role_messages: dict[str, list[dict]] = field(
        default_factory=lambda: {
            "guide": [],
            "doctor": [],
            "chief": [],
        }
    )
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


def _triage_suggestion(patient: PatientRecord, reasoner: str = "rule") -> dict:
    guide = GuideAgent(kb=STATE.kb, reasoner=reasoner)
    context = ConsultationContext(patient=patient)
    context.current_state = HospitalState.TRIAGE
    action = guide.run(context)
    department = action.payload.get("department", STATE.kb.departments[0])
    matched = 0
    department_scores = []
    for candidate in STATE.kb.departments:
        symptoms: set[str] = set()
        for disease in STATE.kb.by_department(candidate):
            symptoms.update(disease.symptoms)
        overlap = len(set(patient.symptoms) & symptoms)
        if candidate == department:
            matched = overlap
        department_scores.append(
            {
                "department": candidate,
                "matched": overlap,
            }
        )
    department_scores.sort(key=lambda item: item["matched"], reverse=True)
    return {
        "department": department,
        "reason": action.payload.get("reason", f"症状匹配 {matched}"),
        "departments": department_scores,
    }


def _doctor_questions(
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


def _doctor_suggestion(
    patient: PatientRecord, department: str, reasoner: str = "rule"
) -> dict:
    doctor = DoctorAgent(
        kb=STATE.kb,
        reasoner=reasoner,
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
    reasoning = doctor._build_reasoning(context, scored) if scored else "无法识别"
    if reasoner == "llm":
        action = doctor._llm_diagnose(context)
        disease = STATE.kb.get(action.payload.get("disease_id", "")) or STATE.kb.by_name(
            action.payload.get("disease_name", "")
        )
        if disease is not None:
            best = disease
            reasoning = action.payload.get("reasoning", reasoning)
    return {
        "candidates": candidates,
        "best_id": best.id if best else "",
        "best_name": best.name if best else "",
        "exams": exams[:6],
        "treatment": list(best.treatments) if best else [],
        "reasoning": reasoning,
        "retrieved_cases": context.retrieved_cases,
        "retrieved_rules": context.retrieved_rules,
    }


def _append_role_message(
    session: AssistantSession,
    role: str,
    sender: str,
    content: str,
    payload: dict | None = None,
    audio_path: str = "",
) -> None:
    message: dict = {
        "sender": sender,
        "role": role,
        "content": content,
        "payload": payload or {},
    }
    if audio_path:
        message["audio_path"] = audio_path
    session.role_messages.setdefault(role, []).append(message)
    STATE.hospital_store.add_message(
        session.session_id, sender, role, content, audio_path
    )


def _assistant_state(session: AssistantSession) -> dict:
    return {
        "session_id": session.session_id,
        "reasoner": session.reasoner,
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
        "role_messages": session.role_messages,
        "pending_questions": list(session.pending_questions),
        "question_index": session.question_index,
        "suggestion": session.suggestion,
        "orders": STATE.hospital_store.list_orders(session.session_id),
    }


def _get_assistant_session(body: dict) -> AssistantSession:
    session = STATE.assistant_sessions.get(str(body.get("session_id", "")))
    if session is None:
        raise ValueError("会话不存在")
    return session


def _guide_reply(session: AssistantSession, content: str) -> str:
    suggestion = _triage_suggestion(session.patient, session.reasoner)
    lines = [f"我的分诊建议仍是「{suggestion['department']}」，依据是{suggestion['reason']}。"]
    mentioned = [dep for dep in STATE.kb.departments if dep in content]
    for dep in mentioned[:2]:
        match = next(
            (item for item in suggestion["departments"] if item["department"] == dep),
            None,
        )
        if match:
            lines.append(
                f"关于「{dep}」：当前匹配 {match['matched']} 项症状，"
                f"而建议科室匹配 {suggestion['departments'][0]['matched']} 项。"
            )
    lines.append("如果你有不同判断，可以直接说明理由，或最后修改科室后再确认。")
    return "；".join(lines)


def _doctor_reply(session: AssistantSession, content: str) -> str:
    if not session.department:
        return "请先完成导医分诊，我再聚焦对应科室的候选疾病。"
    suggestion = _doctor_suggestion(
        session.patient, session.department, session.reasoner
    )
    if any(word in content for word in ["检查", "开检查", "辅助检查"]):
        return f"根据目前信息，建议优先检查：{'、'.join(suggestion['exams'][:5]) or '暂无'}。"
    if any(word in content for word in ["药", "治疗", "开药"]):
        return f"目前治疗参考：{'、'.join(suggestion['treatment'][:5]) or '暂无'}。"
    if any(word in content for word in ["为什么", "理由", "依据", "鉴别"]):
        return f"鉴别诊断依据：{suggestion['reasoning']}"
    return (
        f"当前最可能诊断：{suggestion['best_name']}。"
        "你可以继续和我讨论，也可以让我先追问几个关键症状再下结论。"
    )


def _chief_reply(session: AssistantSession, content: str) -> str:
    if session.stage != "chief":
        return "我目前没有收到会诊请求。主诊医师拿不准时可以请求会诊，我会查看完整历史对话后再给意见。"
    decision = session.decisions.get("doctor", {})
    return (
        f"我已查看本次会话历史。主诊倾向：{decision.get('disease_name', '待定')}。"
        "请主任复核诊断、检查与用药；我会在最终确认后把记录写入医院系统。"
    )


def _start_assistant(body: dict) -> dict:
    patient = _assistant_patient(body)
    if not patient.symptoms:
        raise ValueError("请至少输入一个症状")
    reasoner = str(body.get("reasoner", "rule")).strip().lower()
    if reasoner not in {"rule", "llm"}:
        raise ValueError("无效推理模式")
    session = AssistantSession(
        session_id=uuid.uuid4().hex[:12],
        patient=patient,
        reasoner=reasoner,
    )
    patient_view = {
        "id": patient.patient_id,
        "name": patient.name,
        "gender": patient.gender,
        "age": patient.age,
        "symptoms": list(patient.symptoms),
        "medical_history": list(patient.medical_history),
        "risk_factors": list(patient.risk_factors),
    }
    STATE.hospital_store.create_session(session.session_id, patient_view)
    suggestion = _triage_suggestion(patient, reasoner)
    session.suggestion = suggestion
    _append_role_message(
        session,
        "guide",
        "guide",
        f"根据当前症状，建议先前往「{suggestion['department']}」就诊。",
        payload=suggestion,
    )
    _append_role_message(
        session,
        "guide",
        "guide",
        "我是导医 Agent，只提建议：你可以和我讨论、反驳，最后再确认分诊。",
    )
    _append_role_message(
        session,
        "doctor",
        "doctor",
        "主诊已就位：分诊确认后，我会先追问关键症状，再给出鉴别诊断、检查与用药建议。",
    )
    _append_role_message(
        session,
        "chief",
        "chief",
        "主任会诊通道已就位：主诊拿不准时可以请求会诊，我会查看完整历史对话后给出意见。",
    )
    with STATE.lock:
        STATE.assistant_sessions[session.session_id] = session
    return _assistant_state(session)


def _message_assistant(body: dict) -> dict:
    session = _get_assistant_session(body)
    role = str(body.get("role", ""))
    content = str(body.get("content", "")).strip()
    audio_path = str(body.get("audio_path", "")).strip()
    if role not in {"guide", "doctor", "chief"}:
        raise ValueError(f"无效角色: {role}")
    if not content:
        raise ValueError("消息内容为空")
    if audio_path and not audio_path.startswith("/audio/"):
        raise ValueError("无效音频地址")
    _append_role_message(
        session, role, "user", content, audio_path=audio_path
    )
    reply = {
        "guide": _guide_reply,
        "doctor": _doctor_reply,
        "chief": _chief_reply,
    }[role](session, content)
    _append_role_message(session, role, role, reply)
    return _assistant_state(session)


def _set_reasoner_assistant(body: dict) -> dict:
    session = _get_assistant_session(body)
    reasoner = str(body.get("reasoner", "rule")).strip().lower()
    if reasoner not in {"rule", "llm"}:
        raise ValueError("无效推理模式")
    session.reasoner = reasoner
    return _assistant_state(session)


def _answer_question_assistant(body: dict) -> dict:
    session = _get_assistant_session(body)
    if session.stage != "doctor":
        raise ValueError(f"当前阶段为 {session.stage}，主诊追问只在主诊阶段可用")
    symptom = str(body.get("symptom", "")).strip()
    present = bool(body.get("present", False))
    if not symptom:
        raise ValueError("缺少症状字段")
    if present and symptom not in session.patient.symptoms:
        session.patient.symptoms.append(symptom)
    session.decisions.setdefault("questions", []).append(
        {"symptom": symptom, "present": present}
    )
    _append_role_message(
        session,
        "doctor",
        "user",
        f"{'有' if present else '没有'} {symptom}（主诊追问）",
    )
    session.question_index += 1
    if session.question_index < len(session.pending_questions):
        question = session.pending_questions[session.question_index]
        session.suggestion = {
            "question": question,
            "question_index": session.question_index + 1,
            "total": len(session.pending_questions),
        }
        _append_role_message(
            session,
            "doctor",
            "doctor",
            f"建议补充确认：{question}？",
            payload=session.suggestion,
        )
        return _assistant_state(session)
    session.decisions["questions_done"] = True
    session.suggestion = _doctor_suggestion(
        session.patient, session.department, session.reasoner
    )
    _append_role_message(
        session,
        "doctor",
        "doctor",
        f"追问完成，更新后最可能诊断：{session.suggestion['best_name']}。",
        payload=session.suggestion,
    )
    return _assistant_state(session)


def _resolve_disease(override: str, suggestion: dict) -> Disease:
    disease_id = override or suggestion.get("best_id", "")
    disease = STATE.kb.get(disease_id)
    if disease is None:
        disease = STATE.kb.by_name(override or suggestion.get("best_name", ""))
    if disease is None:
        raise ValueError("未选择有效诊断")
    return disease


def _persist_orders(
    session: AssistantSession, exams: list[str], medications: list[str]
) -> None:
    for name in exams:
        STATE.hospital_store.add_order(session.session_id, "exam", name)
    for name in medications:
        STATE.hospital_store.add_order(session.session_id, "medication", name)


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
        _append_role_message(session, "guide", "user", f"导医确认：{department}")
        STATE.hospital_store.update_session(
            session.session_id, department=department
        )
        questions = _doctor_questions(session.patient, department)
        session.pending_questions = questions
        session.question_index = 0
        session.stage = "doctor"
        if questions:
            first = questions[0]
            session.suggestion = {
                "question": first,
                "question_index": 1,
                "total": len(questions),
            }
            _append_role_message(
                session,
                "doctor",
                "doctor",
                f"主诊想先确认：{first}？",
                payload=session.suggestion,
            )
        else:
            session.suggestion = _doctor_suggestion(
                session.patient, department, session.reasoner
            )
            _append_role_message(
                session,
                "doctor",
                "doctor",
                f"初步鉴别诊断：{session.suggestion['best_name']}。",
                payload=session.suggestion,
            )
        return _assistant_state(session)

    if stage == "doctor":
        if bool(body.get("escalate", False)):
            session.decisions["doctor"] = {
                "escalated": True,
                "reason": override or "主诊判断存在不确定性",
            }
            _append_role_message(
                session,
                "doctor",
                "user",
                "主诊请求主任会诊",
                payload={"escalated": True, "reason": override},
            )
            session.stage = "chief"
            doctor_suggestion = _doctor_suggestion(
                session.patient, session.department, session.reasoner
            )
            session.suggestion = {
                "department": session.department,
                "question_count": len(session.decisions.get("questions", [])),
                "best_id": doctor_suggestion["best_id"],
                "best_name": doctor_suggestion["best_name"],
                "candidates": doctor_suggestion["candidates"],
                "exams": doctor_suggestion["exams"],
                "treatment": doctor_suggestion["treatment"],
                "history": [
                    item.get("content")
                    for items in session.role_messages.values()
                    for item in items
                ][-20:],
            }
            _append_role_message(
                session,
                "chief",
                "chief",
                "主诊请求会诊。我已读取完整历史对话，请主任复核最终诊断、检查与用药。",
                payload=session.suggestion,
            )
            return _assistant_state(session)

        suggestion = session.suggestion or {}
        disease = _resolve_disease(override, suggestion)
        exams = _parse_list(body.get("exams"))
        medications = _parse_list(body.get("medications"))
        session.decisions["doctor"] = {
            "disease_id": disease.id,
            "disease_name": disease.name,
            "accepted": accepted,
            "override": override,
            "exams": exams,
            "medications": medications,
            "reasoning": suggestion.get("reasoning", ""),
        }
        _persist_orders(session, exams, medications)
        STATE.hospital_store.update_session(
            session.session_id,
            department=session.department or "",
            diagnosis_id=disease.id,
            diagnosis_name=disease.name,
            completed=True,
        )
        _append_role_message(
            session,
            "doctor",
            "user",
            f"主诊确认：{disease.name}，检查 {len(exams)} 项，用药 {len(medications)} 项。",
            payload={"disease_id": disease.id, "disease_name": disease.name},
        )
        session.stage = "done"
        session.suggestion = None
        _append_role_message(
            session,
            "doctor",
            "doctor",
            "主诊已下定论，医嘱与处方已写入医院记录系统。",
            payload={"done": True},
        )
        return _assistant_state(session)

    if stage == "chief":
        suggestion = session.suggestion or {}
        disease = _resolve_disease(override, suggestion)
        exams = _parse_list(body.get("exams"))
        medications = _parse_list(body.get("medications"))
        session.decisions["chief"] = {
            "disease_id": disease.id,
            "disease_name": disease.name,
            "accepted": accepted,
            "override": override,
            "exams": exams,
            "medications": medications,
        }
        _persist_orders(session, exams, medications)
        STATE.hospital_store.update_session(
            session.session_id,
            department=session.department or "",
            diagnosis_id=disease.id,
            diagnosis_name=disease.name,
            completed=True,
        )
        session.stage = "done"
        session.suggestion = None
        _append_role_message(
            session,
            "chief",
            "user",
            f"主任确认：{disease.name}，检查 {len(exams)} 项，用药 {len(medications)} 项。",
            payload={"disease_id": disease.id, "disease_name": disease.name},
        )
        _append_role_message(
            session,
            "chief",
            "chief",
            "会诊结论已确认，最终医嘱与处方已写入医院记录系统。",
            payload={"done": True},
        )
        return _assistant_state(session)

    raise ValueError(f"未知阶段: {stage}")


def _save_audio(session_id: str, raw: bytes) -> dict:
    if not session_id or not raw:
        raise ValueError("缺少会话或音频数据")
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{session_id}_{int(time.time() * 1000)}.webm"
    target = AUDIO_DIR / filename
    target.write_bytes(raw)
    return {"audio_path": f"/audio/{filename}", "saved": True}


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
        if path.startswith("/audio/"):
            target = (AUDIO_DIR / path.removeprefix("/audio/")).resolve()
            if (
                not str(target).startswith(str(AUDIO_DIR.resolve()))
                or not target.is_file()
            ):
                _json_response(self, {"error": "not found"}, status=404)
                return
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/webm")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/assistant/audio":
            query = parse_qs(urlparse(self.path).query)
            session_id = query.get("session_id", [""])[0]
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b""
            try:
                _json_response(self, _save_audio(session_id, raw))
            except ValueError as exc:
                _json_response(self, {"error": str(exc)}, status=400)
            return
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
            if path == "/api/assistant/message":
                _json_response(self, _message_assistant(body))
                return
            if path == "/api/assistant/reasoner":
                _json_response(self, _set_reasoner_assistant(body))
                return
            if path == "/api/assistant/answer_question":
                _json_response(self, _answer_question_assistant(body))
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
