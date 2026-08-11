"""Small diagnostic evaluation used as the D3-D4 acceptance test."""

from __future__ import annotations

from collections import defaultdict

from medagent_hospital.agents.doctor import DoctorAgent
from medagent_hospital.agents.nurse import NurseAgent
from medagent_hospital.agents.patient import PatientAgent
from medagent_hospital.knowledge import KnowledgeBase, load_knowledge_base
from medagent_hospital.simulacrum.patient_generator import PatientGenerator
from medagent_hospital.simulacrum.runtime import HospitalRuntime


def build_runtime(
    kb: KnowledgeBase | None = None,
    reasoner: str = "rule",
) -> tuple[HospitalRuntime, KnowledgeBase]:
    kb = kb or load_knowledge_base()
    runtime = HospitalRuntime(
        patient_agent=PatientAgent(),
        nurse_agent=NurseAgent(kb=kb),
        doctor_agent=DoctorAgent(kb=kb, reasoner=reasoner),
    )
    return runtime, kb


def run_small_diagnostic_test(
    patients_per_department: int = 5,
    seed: int = 42,
    reasoner: str = "rule",
) -> dict:
    kb = load_knowledge_base()
    runtime, _ = build_runtime(kb, reasoner)
    generator = PatientGenerator(kb, seed=seed)
    total = 0
    correct = 0
    by_department: dict[str, dict] = {}
    by_disease: dict[str, dict] = defaultdict(lambda: {"total": 0, "correct": 0})

    for department in kb.departments:
        department_correct = 0
        for patient in generator.generate_batch(department, count=patients_per_department):
            context = runtime.run_episode(patient)
            is_correct = context.diagnosis_id == patient.ground_truth_disease_id
            total += 1
            correct += int(is_correct)
            department_correct += int(is_correct)
            stat = by_disease[patient.ground_truth_disease_id]
            stat["total"] += 1
            stat["correct"] += int(is_correct)
        by_department[department] = {
            "total": patients_per_department,
            "correct": department_correct,
            "accuracy": department_correct / patients_per_department,
        }

    return {
        "total": total,
        "correct": correct,
        "accuracy": correct / total,
        "by_department": by_department,
        "by_disease": {key: dict(value) for key, value in by_disease.items()},
    }
