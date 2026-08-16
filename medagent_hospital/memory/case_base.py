"""Medical case base: successful cases retrieved to support future diagnoses."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class MedicalCase:
    patient: dict[str, Any]
    diagnosis: str
    treatment: str
    diagnosis_id: str = ""
    outcome: str = "recovered"
    created_at: float = 0.0
    importance: float = 1.0
    retrieval_count: int = 0


@dataclass
class CaseHit:
    case: MedicalCase
    score: float


class MedicalCaseBase:
    """Memory-stream case store.

    Retrieval score combines relevance (Jaccard on symptoms/exams), recency
    (exponential decay), importance and retrieval reinforcement, inspired by
    Stanford Generative Agents' memory stream.
    """

    def __init__(
        self,
        dedup_threshold: float = 0.0,
        decay_rate: float = 1e-4,
        reinforcement_factor: float = 0.1,
    ) -> None:
        self._cases: list[MedicalCase] = []
        self.dedup_threshold = dedup_threshold
        self.decay_rate = decay_rate
        self.reinforcement_factor = reinforcement_factor
        self.skipped = 0

    def add(self, case: MedicalCase) -> bool:
        if case.created_at <= 0:
            case.created_at = time.time()
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

    def retrieve(
        self,
        query: dict[str, Any] | Any,
        top_k: int = 3,
        *,
        now: float | None = None,
    ) -> list[CaseHit]:
        now = now if now is not None else time.time()
        scored: list[CaseHit] = []
        for case in self._cases:
            relevance = self._combined_score(query, case)
            if relevance <= 0:
                continue
            age = max(0.0, now - case.created_at)
            recency = math.exp(-self.decay_rate * age)
            reinforcement = 1.0 + self.reinforcement_factor * case.retrieval_count
            score = relevance * recency * case.importance * reinforcement
            scored.append(CaseHit(case=case, score=score))
        scored.sort(key=lambda hit: hit.score, reverse=True)
        hits = scored[:top_k]
        for hit in hits:
            hit.case.retrieval_count += 1
        return hits

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
