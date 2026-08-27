"""Tests for the model-proposal, verifier-owned Skill distillation boundary."""

import json

from medagent_hospital.knowledge import load_knowledge_base
from medagent_hospital.llm.base import LLMBackend
from medagent_hospital.memory.skill_distiller import SkillDistiller
from medagent_hospital.simulacrum.models import ConsultationContext, PatientRecord


class FakeBackend(LLMBackend):
    name = "fake"

    def __init__(self, text: str) -> None:
        self.text = text

    def chat(self, messages, **kwargs) -> str:
        return self.text


def make_context() -> tuple[PatientRecord, ConsultationContext]:
    patient = PatientRecord(
        patient_id="skill-test",
        name="test",
        gender="any",
        age=50,
        symptoms=["observed symptom"],
        medical_history=[],
        risk_factors=[],
        exam_results=[],
        ground_truth_disease_id="DERM-001",
        ground_truth_disease_name="",
    )
    context = ConsultationContext(patient=patient, department="皮肤科")
    context.diagnosis_id = "DERM-002"
    return patient, context


def test_distiller_accepts_valid_candidate_without_writing_a_base() -> None:
    kb = load_knowledge_base()
    exam = kb.get("DERM-001").examinations[0].name
    payload = json.dumps(
        {
            "skill_name": "test skill",
            "trigger": ["observed symptom"],
            "action": "add_exam",
            "target_exam": exam,
            "favor": "DERM-001",
            "against": "DERM-002",
        },
        ensure_ascii=False,
    )
    patient, context = make_context()
    skill = SkillDistiller(FakeBackend(payload), kb).distill(
        patient, context, skill_id="S-test"
    )
    assert skill is not None
    assert skill.skill_id == "S-test"
    assert skill.source == "llm_distillation"
    assert skill.action == "add_exam"


def test_distiller_rejects_unknown_or_unobserved_candidate_fields() -> None:
    kb = load_knowledge_base()
    patient, context = make_context()
    payload = (
        '{"skill_name":"hallucinated","trigger":["not observed"],'
        '"action":"execute_treatment","target_exam":"unknown",'
        '"favor":"OTHER","against":"DERM-002"}'
    )
    assert SkillDistiller(FakeBackend(payload), kb).distill(
        patient, context, skill_id="S-rejected"
    ) is None
