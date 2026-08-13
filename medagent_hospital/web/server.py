"""Stdlib demo server for the MedAgent-Hospital dashboard.

Runs the pixel-hospital simulation UI and the evolution analysis views.
"""

from __future__ import annotations

import json
import os
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

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

STATIC_DIR = Path(__file__).resolve().parent / "static"


class DemoState:
    def __init__(self) -> None:
        self.kb = load_knowledge_base()
        self.latest_evolution: dict | None = None
        self.evolved_registry = None
        self.guide_case_base = MedicalCaseBase()
        self.guide_experience_base = ExperienceBase()
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
        except Exception as exc:  # pragma: no cover - defensive API boundary
            _json_response(self, {"error": str(exc)}, status=500)
            return
        _json_response(self, {"error": "not found"}, status=404)

    def _serve_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
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
