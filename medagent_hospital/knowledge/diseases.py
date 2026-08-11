"""Structured disease knowledge base with JSON loader and validation.

Data is for algorithm demonstration and research only, NOT clinical use.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from medagent_hospital.config import PROJECT_ROOT

DEFAULT_KB_PATH = PROJECT_ROOT / "data" / "knowledge_base.json"


@dataclass(frozen=True)
class Examination:
    name: str
    findings: str


@dataclass(frozen=True)
class PatientProfile:
    age_range: tuple[int, int]
    gender_bias: str
    symptom_weights: dict[str, float]
    history_bias: tuple[str, ...]
    exam_hit_rate: float

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PatientProfile":
        return cls(
            age_range=(int(raw["age_range"][0]), int(raw["age_range"][1])),
            gender_bias=str(raw["gender_bias"]),
            symptom_weights={str(k): float(v) for k, v in raw["symptom_weights"].items()},
            history_bias=tuple(str(x) for x in raw.get("history_bias", [])),
            exam_hit_rate=float(raw["exam_hit_rate"]),
        )


@dataclass(frozen=True)
class Disease:
    id: str
    name: str
    department: str
    symptoms: tuple[str, ...]
    risk_factors: tuple[str, ...] = ()
    examinations: tuple[Examination, ...] = ()
    treatments: tuple[str, ...] = ()
    distinguishing_features: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    patient_profile: PatientProfile | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Disease":
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            department=str(raw["department"]),
            symptoms=tuple(str(x) for x in raw["symptoms"]),
            risk_factors=tuple(str(x) for x in raw.get("risk_factors", [])),
            examinations=tuple(
                Examination(name=str(exam["name"]), findings=str(exam["findings"]))
                for exam in raw.get("examinations", [])
            ),
            treatments=tuple(str(x) for x in raw.get("treatments", [])),
            distinguishing_features=tuple(str(x) for x in raw.get("distinguishing_features", [])),
            aliases=tuple(str(x) for x in raw.get("aliases", [])),
            patient_profile=(
                PatientProfile.from_dict(raw["patient_profile"]) if raw.get("patient_profile") else None
            ),
        )


class KnowledgeBase:
    def __init__(self, diseases: list[Disease], departments: list[str], source: str | Path | None = None) -> None:
        self.diseases = diseases
        self.departments = list(departments)
        self.source = Path(source) if source else None
        self._by_id = {disease.id: disease for disease in diseases}
        self._by_name: dict[str, Disease] = {}
        for disease in diseases:
            self._by_name[disease.name] = disease
            for alias in disease.aliases:
                self._by_name[alias] = disease

    def get(self, disease_id: str) -> Disease | None:
        return self._by_id.get(disease_id)

    def by_name(self, name: str) -> Disease | None:
        return self._by_name.get(name)

    def by_department(self, department: str) -> list[Disease]:
        return [disease for disease in self.diseases if disease.department == department]

    def validate(self) -> list[str]:
        """Return a list of data quality issues; empty list means valid."""
        errors: list[str] = []
        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        department_set = set(self.departments)

        if not 40 <= len(self.diseases) <= 50:
            errors.append(f"疾病数量应为 40-50，当前为 {len(self.diseases)}")
        if len(self.departments) < 6:
            errors.append(f"科室数量应不少于 6，当前为 {len(self.departments)}")

        for disease in self.diseases:
            label = f"{disease.id} {disease.name}"
            if disease.id in seen_ids:
                errors.append(f"疾病 id 重复: {disease.id}")
            seen_ids.add(disease.id)
            if disease.name in seen_names:
                errors.append(f"疾病名重复: {disease.name}")
            seen_names.add(disease.name)
            if disease.department not in department_set:
                errors.append(f"{label} 科室不在知识库科室列表: {disease.department}")
            if not disease.symptoms:
                errors.append(f"{label} 缺少症状")
            if not disease.risk_factors:
                errors.append(f"{label} 缺少危险因素")
            if not disease.examinations:
                errors.append(f"{label} 缺少检查")
            if not disease.treatments:
                errors.append(f"{label} 缺少治疗方案")
            if not disease.distinguishing_features:
                errors.append(f"{label} 缺少鉴别要点")

            profile = disease.patient_profile
            if profile is None:
                errors.append(f"{label} 缺少 patient_profile")
                continue
            low, high = profile.age_range
            if not (0 <= low <= high <= 120):
                errors.append(f"{label} 年龄范围非法: {profile.age_range}")
            if profile.gender_bias not in {"male", "female", "any"}:
                errors.append(f"{label} gender_bias 非法: {profile.gender_bias}")
            if set(profile.symptom_weights) != set(disease.symptoms):
                errors.append(f"{label} symptom_weights 与 symptoms 不一致")
            for symptom, weight in profile.symptom_weights.items():
                if not 0 < weight <= 1:
                    errors.append(f"{label} 症状权重非法: {symptom}={weight}")
            if not 0 < profile.exam_hit_rate <= 1:
                errors.append(f"{label} exam_hit_rate 非法: {profile.exam_hit_rate}")

        return errors

    def __len__(self) -> int:
        return len(self.diseases)


def load_knowledge_base(path: str | Path | None = None) -> KnowledgeBase:
    path = Path(path) if path else DEFAULT_KB_PATH
    with open(path, encoding="utf-8") as file:
        raw = json.load(file)
    diseases = [Disease.from_dict(item) for item in raw["diseases"]]
    return KnowledgeBase(diseases, raw["departments"], source=path)
