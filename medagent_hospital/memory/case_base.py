"""Medical case base: successful cases retrieved to support future diagnoses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MedicalCase:
    patient: dict[str, Any]
    diagnosis: str
    treatment: str
    diagnosis_id: str = ""
    outcome: str = "recovered"


@dataclass
class CaseHit:
    case: MedicalCase
    score: float


class MedicalCaseBase:
    """Jaccard-similarity case store; embedding retrieval can replace the scoring later."""

    def __init__(self, dedup_threshold: float = 0.0) -> None:
        self._cases: list[MedicalCase] = []
        self.dedup_threshold = dedup_threshold
        self.skipped = 0

    def add(self, case: MedicalCase) -> bool:
        if self.dedup_threshold > 0 and self._similarity_to_existing(case) >= self.dedup_threshold:
            self.skipped += 1
            return False
        self._cases.append(case)
        return True

    def _similarity_to_existing(self, case: MedicalCase) -> float:
        best = 0.0
        for existing in self._cases:
            best = max(best, self._combined_score(case.patient, existing))
        return best

    def retrieve(self, query: dict[str, Any] | Any, top_k: int = 3) -> list[CaseHit]:
        scored: list[CaseHit] = []
        for case in self._cases:
            scored.append(CaseHit(case=case, score=self._combined_score(query, case)))
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:top_k]

    @staticmethod
    def _feature_sets(query: dict[str, Any] | Any) -> tuple[set[str], set[str]]:
        if isinstance(query, dict):
            return set(query.get("symptoms", [])), set(query.get("exam_names", []))
        symptoms = query.symptoms if hasattr(query, "symptoms") else []
        exam_names = []
        if hasattr(query, "exam_results"):
            exam_names = [exam.name for exam in query.exam_results if exam.is_abnormal()]
        return set(symptoms), set(exam_names)

    @staticmethod
    def _jaccard(left: set[str], right: set[str]) -> float:
        union = left | right
        return len(left & right) / len(union) if union else 0.0

    def _combined_score(self, query: dict[str, Any] | Any, case: MedicalCase) -> float:
        query_symptoms, query_exams = self._feature_sets(query)
        case_symptoms = set(case.patient.get("symptoms", []))
        case_exams = set(case.patient.get("exam_names", []))
        if not (query_symptoms | case_symptoms or query_exams | case_exams):
            return 0.0
        symptom_score = self._jaccard(query_symptoms, case_symptoms)
        exam_score = self._jaccard(query_exams, case_exams)
        # Exam evidence is weighted higher than mixed symptoms on purpose.
        return (symptom_score + 2.0 * exam_score) / 3.0

    def __len__(self) -> int:
        return len(self._cases)
