"""Patient agent generation: sample structured patients from the knowledge base."""

from __future__ import annotations

import random

from medagent_hospital.knowledge import Disease, KnowledgeBase
from medagent_hospital.simulacrum.models import ExamResult, NORMAL_FINDING, PatientRecord

MALE_NAMES = ["张伟", "李强", "王磊", "刘洋", "陈刚", "杨帆", "赵鹏", "黄志强", "周杰", "吴勇"]
FEMALE_NAMES = ["王芳", "李娜", "张敏", "刘静", "陈燕", "杨雪", "赵婷", "黄丽", "周琳", "吴倩"]


class PatientGenerator:
    """Generate diverse patient records by sampling a disease's profile."""

    def __init__(
        self,
        kb: KnowledgeBase,
        seed: int | None = None,
        distractor_probability: float = 0.25,
        symptom_omission_probability: float = 0.0,
        exam_hit_rate_override: float | None = None,
    ) -> None:
        self.kb = kb
        self.rng = random.Random(seed)
        self.distractor_probability = distractor_probability
        self.symptom_omission_probability = symptom_omission_probability
        self.exam_hit_rate_override = exam_hit_rate_override
        self._counter = 0

    def generate(
        self,
        department: str | None = None,
        disease_id: str | None = None,
    ) -> PatientRecord:
        disease = self._pick_disease(department, disease_id)
        profile = disease.patient_profile
        if profile is None:
            raise ValueError(f"疾病缺少 patient_profile: {disease.name}")

        self._counter += 1
        gender = self._sample_gender(profile.gender_bias)
        patient_id = f"P{self._counter:05d}"
        name = self.rng.choice(MALE_NAMES if gender == "male" else FEMALE_NAMES)
        age = self.rng.randint(profile.age_range[0], profile.age_range[1])
        symptoms = self._sample_symptoms(disease)
        medical_history = (
            self.rng.sample(profile.history_bias, k=min(2, len(profile.history_bias)))
            if profile.history_bias
            else []
        )
        risk_factors = (
            self.rng.sample(list(disease.risk_factors), k=min(2, len(disease.risk_factors)))
            if disease.risk_factors
            else []
        )
        hit_rate = (
            profile.exam_hit_rate
            if self.exam_hit_rate_override is None
            else self.exam_hit_rate_override
        )
        exam_results = self._sample_exams(disease, hit_rate)

        return PatientRecord(
            patient_id=patient_id,
            name=name,
            gender=gender,
            age=age,
            symptoms=symptoms,
            medical_history=medical_history,
            risk_factors=risk_factors,
            exam_results=exam_results,
            ground_truth_disease_id=disease.id,
            ground_truth_disease_name=disease.name,
        )

    def generate_batch(
        self,
        department: str | None = None,
        count: int = 5,
        disease_ids: list[str] | None = None,
    ) -> list[PatientRecord]:
        if disease_ids:
            return [self.generate(disease_id=disease_id) for disease_id in disease_ids]
        return [self.generate(department=department) for _ in range(count)]

    def _pick_disease(self, department: str | None, disease_id: str | None) -> Disease:
        if disease_id:
            disease = self.kb.get(disease_id)
            if disease is None:
                raise ValueError(f"未知疾病 id: {disease_id}")
            return disease
        pool = self.kb.by_department(department) if department else self.kb.diseases
        if not pool:
            raise ValueError(f"科室没有疾病: {department}")
        return self.rng.choice(pool)

    def _sample_gender(self, bias: str) -> str:
        if bias == "male":
            return "male"
        if bias == "female":
            return "female"
        return self.rng.choice(["male", "female"])

    def _sample_symptoms(self, disease: Disease) -> list[str]:
        weights = disease.patient_profile.symptom_weights
        selected = [s for s in disease.symptoms if self.rng.random() < weights.get(s, 0.6)]
        if len(selected) < 2:
            ordered = sorted(disease.symptoms, key=lambda s: weights.get(s, 0.0), reverse=True)
            for symptom in ordered:
                if symptom not in selected:
                    selected.append(symptom)
                if len(selected) >= 2:
                    break
        if self.rng.random() < self.distractor_probability:
            distractor = self._sample_distractor(disease)
            if distractor is not None:
                selected.append(distractor)
        if self.symptom_omission_probability > 0 and len(selected) > 1:
            kept = [
                symptom
                for symptom in selected
                if self.rng.random() >= self.symptom_omission_probability
            ]
            if not kept:
                kept = [max(selected, key=lambda s: weights.get(s, 0.0))]
            selected = kept
        return selected

    def _sample_distractor(self, disease: Disease) -> str | None:
        pool: list[str] = []
        for other in self.kb.by_department(disease.department):
            if other.id != disease.id:
                pool.extend(other.symptoms)
        unique = list(dict.fromkeys(pool))
        candidates = [symptom for symptom in unique if symptom not in disease.symptoms]
        return self.rng.choice(candidates) if candidates else None

    def _sample_exams(self, disease: Disease, hit_rate: float) -> list[ExamResult]:
        results = []
        for exam in disease.examinations:
            if self.rng.random() < hit_rate:
                results.append(ExamResult(name=exam.name, findings=exam.findings))
            else:
                results.append(ExamResult(name=exam.name, findings=NORMAL_FINDING))
        return results
