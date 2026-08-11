"""Memory manager: write successful cases, reflect on failures, validate rules."""

from __future__ import annotations

from medagent_hospital.agents.doctor import DoctorAgent
from medagent_hospital.agents.nurse import NurseAgent
from medagent_hospital.agents.patient import PatientAgent
from medagent_hospital.knowledge import KnowledgeBase
from medagent_hospital.memory.case_base import MedicalCase, MedicalCaseBase
from medagent_hospital.memory.experience_base import ExperienceBase, ExperienceRule
from medagent_hospital.simulacrum.models import ConsultationContext, PatientRecord
from medagent_hospital.simulacrum.patient_generator import PatientGenerator
from medagent_hospital.simulacrum.runtime import HospitalRuntime


class MemoryManager:
    """Maintain a doctor's case base and experience base during treatment."""

    def __init__(
        self,
        kb: KnowledgeBase,
        case_base: MedicalCaseBase | None = None,
        experience_base: ExperienceBase | None = None,
        validation_patients: list[PatientRecord] | None = None,
        rule_strength: float = 0.6,
        reasoner: str = "rule",
    ) -> None:
        self.kb = kb
        self.case_base = case_base if case_base is not None else MedicalCaseBase()
        self.experience_base = (
            experience_base if experience_base is not None else ExperienceBase()
        )
        self.validation_patients = (
            validation_patients if validation_patients is not None else []
        )
        self.rule_strength = rule_strength
        self.reasoner = reasoner

    @classmethod
    def with_default_validation(
        cls,
        kb: KnowledgeBase,
        patients_per_disease: int = 2,
        seed: int = 2024,
        **kwargs,
    ) -> "MemoryManager":
        generator = PatientGenerator(kb, seed=seed)
        patients: list[PatientRecord] = []
        for disease in kb.diseases:
            for _ in range(patients_per_disease):
                patients.append(generator.generate(disease_id=disease.id))
        return cls(kb, validation_patients=patients, **kwargs)

    def update(self, context: ConsultationContext, patient: PatientRecord) -> str:
        """Learn from one completed episode: add cases on success, rules on failure."""
        self._record_rule_stats(context, patient)
        if context.diagnosis_id == patient.ground_truth_disease_id:
            if any(exam.is_abnormal() for exam in context.exam_results):
                self.case_base.add(self._to_case(context, patient))
                return "case_added"
            return "case_skipped_no_evidence"
        rule = self.reflect(patient, context)
        if rule is None:
            return "no_rule"
        if self.validate_rule(rule):
            self.experience_base.add(rule)
            return "rule_added"
        return "rule_discarded"

    def _record_rule_stats(self, context: ConsultationContext, patient: PatientRecord) -> None:
        """Update survival statistics for rules that were used in this episode."""
        for hit in context.retrieved_rules:
            rule = self.experience_base.get(hit.get("rule_id", ""))
            if rule is None:
                continue
            rule.validations += 1
            if (
                context.diagnosis_id == patient.ground_truth_disease_id
                and rule.favor == patient.ground_truth_disease_id
            ):
                rule.successes += 1

    def reflect(self, patient: PatientRecord, context: ConsultationContext) -> ExperienceRule | None:
        """Generate a structured experience rule from a misdiagnosis."""
        true = self.kb.get(patient.ground_truth_disease_id)
        wrong = self.kb.get(context.diagnosis_id)
        if true is None or wrong is None or true.id == wrong.id:
            return None
        wrong_symptoms = set(wrong.symptoms)
        trigger = [symptom for symptom in patient.symptoms if symptom not in wrong_symptoms]
        true_exam_names = {exam.name for exam in true.examinations}
        wrong_exam_names = {exam.name for exam in wrong.examinations}
        for exam in context.exam_results:
            if (
                exam.is_abnormal()
                and exam.name in true_exam_names
                and exam.name not in wrong_exam_names
                and exam.name not in trigger
            ):
                trigger.append(exam.name)
        if not trigger:
            return None
        rule_text = f"当出现 {'、'.join(trigger)} 时，优先考虑 {true.name} 而非 {wrong.name}"
        return ExperienceRule(
            trigger=tuple(trigger),
            rule=rule_text,
            favor=true.id,
            against=wrong.id,
            strength=self.rule_strength,
        )

    def validate_rule(self, rule: ExperienceRule) -> bool:
        """Keep a rule only if it does not hurt accuracy on the validation cohort."""
        if not self.validation_patients:
            return True
        before = self._evaluate(self.experience_base)
        candidate_base = self.experience_base.copy()
        candidate_base.add(rule)
        after = self._evaluate(candidate_base)
        return after >= before

    def _evaluate(self, experience_base: ExperienceBase) -> int:
        doctor = DoctorAgent(
            kb=self.kb,
            case_base=self.case_base,
            experience_base=experience_base,
            reasoner=self.reasoner,
        )
        runtime = HospitalRuntime(
            patient_agent=PatientAgent(),
            nurse_agent=NurseAgent(kb=self.kb),
            doctor_agent=doctor,
        )
        correct = 0
        for patient in self.validation_patients:
            context = runtime.run_episode(patient)
            correct += int(context.diagnosis_id == patient.ground_truth_disease_id)
        return correct

    def _to_case(self, context: ConsultationContext, patient: PatientRecord) -> MedicalCase:
        abnormal_exams = [exam.name for exam in context.exam_results if exam.is_abnormal()]
        return MedicalCase(
            patient={"symptoms": list(patient.symptoms), "exam_names": abnormal_exams},
            diagnosis=patient.ground_truth_disease_name,
            diagnosis_id=patient.ground_truth_disease_id,
            treatment="；".join(context.treatment),
        )
