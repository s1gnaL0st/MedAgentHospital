"""Nurse agent: triage and examination execution (rule-based)."""

from __future__ import annotations

from medagent_hospital.agents.base import Agent
from medagent_hospital.knowledge import KnowledgeBase
from medagent_hospital.llm.base import LLMBackend, RuleBackend
from medagent_hospital.simulacrum.models import Action, ConsultationContext, HospitalState, PatientRecord


class NurseAgent(Agent):
    role = "nurse"

    def __init__(
        self,
        name: str = "分诊护士",
        llm: LLMBackend | None = None,
        kb: KnowledgeBase | None = None,
    ) -> None:
        super().__init__(name, llm or RuleBackend())
        self.kb = kb
        self._department_symptoms = self._build_department_symptoms() if kb else {}

    def run(self, context: ConsultationContext) -> Action:
        if context.current_state == HospitalState.TRIAGE:
            department, matched = self._triage(context.patient)
            return Action(
                "triage",
                {"department": department, "reason": f"命中症状 {matched}"},
            )
        if context.current_state == HospitalState.SYMPTOM_QUESTION:
            return self._ask_symptom(context)
        if context.current_state == HospitalState.EXAMINATION:
            results = context.patient.exam_results_by_names(context.ordered_exams)
            return Action(
                "perform_exams",
                {
                    "exam_results": [
                        {"name": result.name, "findings": result.findings}
                        for result in results
                    ]
                },
            )
        return Action("idle", {})

    def _ask_symptom(self, context: ConsultationContext) -> Action:
        department = context.department
        diseases = (
            self.kb.by_department(department)
            if department and self.kb
            else (self.kb.diseases if self.kb else [])
        )
        observed = set(context.patient.symptoms)
        asked = set(context.asked_symptoms)
        candidates: list[tuple[float, str]] = []
        for disease in diseases:
            if not disease.patient_profile:
                continue
            for symptom, weight in disease.patient_profile.symptom_weights.items():
                if symptom not in observed and symptom not in asked:
                    candidates.append((weight, symptom))
        if not candidates:
            return Action("no_more_questions", {})
        candidates.sort(key=lambda item: item[0], reverse=True)
        symptom = candidates[0][1]
        return Action(
            "ask_symptom",
            {"symptom": symptom, "question": f"请问您是否有{symptom}？"},
        )

    def _build_department_symptoms(self) -> dict[str, set[str]]:
        mapping: dict[str, set[str]] = {}
        for department in self.kb.departments:
            symptoms: set[str] = set()
            for disease in self.kb.by_department(department):
                symptoms.update(disease.symptoms)
            mapping[department] = symptoms
        return mapping

    def _triage(self, patient: PatientRecord) -> tuple[str, int]:
        patient_symptoms = set(patient.symptoms)
        best_department = None
        best_matched = -1
        for department, symptoms in self._department_symptoms.items():
            matched = len(patient_symptoms & symptoms)
            if matched > best_matched:
                best_department = department
                best_matched = matched
        return best_department or "心内科", best_matched
