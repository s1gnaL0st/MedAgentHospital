"""Guide agent (导医): knows every department and guides registration.

The guide has its own case base / experience base so triage guidance can
improve from successful and failed registrations.
"""

from __future__ import annotations

import json

from medagent_hospital.agents.base import Agent
from medagent_hospital.knowledge import KnowledgeBase, load_knowledge_base
from medagent_hospital.llm.base import LLMBackend, RuleBackend, build_llm_backend
from medagent_hospital.memory.case_base import MedicalCase, MedicalCaseBase
from medagent_hospital.memory.experience_base import ExperienceBase, ExperienceRule
from medagent_hospital.simulacrum.models import Action, ConsultationContext, HospitalState, PatientRecord


class GuideAgent(Agent):
    role = "guide"

    def __init__(
        self,
        name: str = "导医",
        llm: LLMBackend | None = None,
        kb: KnowledgeBase | None = None,
        reasoner: str = "rule",
        case_base: MedicalCaseBase | None = None,
        experience_base: ExperienceBase | None = None,
    ) -> None:
        if llm is None and reasoner == "llm":
            llm = build_llm_backend()
        super().__init__(name, llm or RuleBackend())
        self.kb = kb or load_knowledge_base()
        self.reasoner = reasoner
        self.case_base = case_base if case_base is not None else MedicalCaseBase()
        self.experience_base = experience_base if experience_base is not None else ExperienceBase()

    def run(self, context: ConsultationContext) -> Action:
        if context.current_state == HospitalState.TRIAGE:
            return self._triage(context)
        return Action("idle", {})

    def _triage(self, context: ConsultationContext) -> Action:
        if self.reasoner == "llm":
            department = self._llm_triage(context)
            if department:
                return Action("triage", {"department": department, "reason": "导医综合判断"})
        department, matched = self._rule_triage(context.patient)
        return Action("triage", {"department": department, "reason": f"症状匹配 {matched}"})

    def _rule_triage(self, patient: PatientRecord) -> tuple[str, int]:
        best_department = None
        best_matched = -1
        patient_symptoms = set(patient.symptoms)
        for department in self.kb.departments:
            symptoms: set[str] = set()
            for disease in self.kb.by_department(department):
                symptoms.update(disease.symptoms)
            matched = len(patient_symptoms & symptoms)
            if matched > best_matched:
                best_department = department
                best_matched = matched
        return best_department or self.kb.departments[0], best_matched

    def _llm_triage(self, context: ConsultationContext) -> str | None:
        departments = "、".join(self.kb.departments)
        prompt = (
            f"病人症状：{'、'.join(context.patient.symptoms)}\n"
            f"请从以下科室中推荐最合适的一个：{departments}\n"
            '只输出 JSON：{"department": "...", "reasoning": "..."}'
        )
        try:
            text = self.llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=120,
            )
        except Exception:
            return None
        parsed = self._parse_json(text)
        if parsed and parsed.get("department") in self.kb.departments:
            return str(parsed["department"])
        return None

    def update_memory(self, context: ConsultationContext, patient: PatientRecord) -> str:
        disease = self.kb.get(patient.ground_truth_disease_id)
        if disease is None:
            return "no_update"
        true_department = disease.department
        if context.department == true_department:
            self.case_base.add(
                MedicalCase(
                    patient={"symptoms": list(patient.symptoms), "exam_names": []},
                    diagnosis=true_department,
                    diagnosis_id=true_department,
                    treatment="",
                )
            )
            return "case_added"
        rule = ExperienceRule(
            trigger=tuple(patient.symptoms),
            rule=f"出现这些症状时引导至{true_department}",
            favor=true_department,
            against=context.department or "",
        )
        self.experience_base.add(rule)
        return "rule_added"

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None
