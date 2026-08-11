"""Patient agent: reports symptoms, registers, and reports recovery."""

from __future__ import annotations

from medagent_hospital.agents.base import Agent
from medagent_hospital.knowledge import KnowledgeBase, load_knowledge_base
from medagent_hospital.llm.base import LLMBackend, RuleBackend
from medagent_hospital.simulacrum.models import Action, ConsultationContext, HospitalState


class PatientAgent(Agent):
    role = "patient"

    def __init__(
        self,
        name: str = "病人Agent",
        llm: LLMBackend | None = None,
        kb: KnowledgeBase | None = None,
    ) -> None:
        super().__init__(name, llm or RuleBackend())
        self.kb = kb or load_knowledge_base()

    def run(self, context: ConsultationContext) -> Action:
        patient = context.patient
        if context.current_state == HospitalState.DISEASE_ONSET:
            return Action("report_symptoms", patient.doctor_view())
        if context.current_state == HospitalState.REGISTRATION:
            return Action("register", {"patient_id": patient.patient_id, "name": patient.name})
        if context.current_state == HospitalState.SYMPTOM_ANSWER:
            symptom = context.pending_question
            disease = self.kb.get(patient.ground_truth_disease_id)
            present = bool(
                disease
                and symptom
                and symptom in disease.symptoms
                and symptom not in patient.symptoms
            )
            return Action(
                "answer_symptom",
                {"symptom": symptom, "present": present, "text": "有" if present else "没有"},
            )
        if context.current_state == HospitalState.FOLLOW_UP:
            return Action("recover", {"recovered": True, "patient_id": patient.patient_id})
        return Action("idle", {})
