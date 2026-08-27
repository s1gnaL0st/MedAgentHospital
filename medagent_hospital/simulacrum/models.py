"""Shared data models for the hospital simulacrum."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

NORMAL_FINDING = "未见明显异常"
_NEGATIVE_PATTERNS = ("未见明显异常", "无异常", "多正常", "正常")


class HospitalState(str, Enum):
    DISEASE_ONSET = "disease_onset"
    TRIAGE = "triage"
    REGISTRATION = "registration"
    SYMPTOM_QUESTION = "symptom_question"
    SYMPTOM_ANSWER = "symptom_answer"
    CONSULTATION = "consultation"
    EXAMINATION = "examination"
    DIAGNOSIS = "diagnosis"
    CONSULTATION_ROUND = "consultation_round"
    CONSULTATION_SUMMARY = "consultation_summary"
    TREATMENT = "treatment"
    FOLLOW_UP = "follow_up"
    END = "end"


@dataclass
class ExamResult:
    name: str
    findings: str

    def is_abnormal(self) -> bool:
        return not any(pattern in self.findings for pattern in _NEGATIVE_PATTERNS)


@dataclass
class PatientRecord:
    patient_id: str
    name: str
    gender: str
    age: int
    symptoms: list[str]
    medical_history: list[str]
    risk_factors: list[str]
    exam_results: list[ExamResult]
    ground_truth_disease_id: str
    ground_truth_disease_name: str

    def exam_results_by_names(self, names: list[str]) -> list[ExamResult]:
        wanted = set(names)
        return [exam for exam in self.exam_results if exam.name in wanted]

    def doctor_view(self) -> dict[str, Any]:
        """Public patient info; ground truth is intentionally excluded."""
        return {
            "name": self.name,
            "gender": self.gender,
            "age": self.age,
            "symptoms": list(self.symptoms),
            "medical_history": list(self.medical_history),
            "risk_factors": list(self.risk_factors),
        }


@dataclass
class Action:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConsultationContext:
    patient: PatientRecord
    current_state: HospitalState | None = None
    department: str | None = None
    triage_reason: str = ""
    ordered_exams: list[str] = field(default_factory=list)
    exam_results: list[ExamResult] = field(default_factory=list)
    diagnosis_id: str = ""
    diagnosis_name: str = ""
    diagnosis_reasoning: str = ""
    scores: dict[str, float] = field(default_factory=dict)
    retrieved_cases: list[dict[str, Any]] = field(default_factory=list)
    retrieved_rules: list[dict[str, Any]] = field(default_factory=list)
    memory_events: list[dict[str, Any]] = field(default_factory=list)
    nurse_questions: int = 0
    asked_symptoms: list[str] = field(default_factory=list)
    pending_question: str = ""
    consultation_round: int = 0
    consultation_triggered: bool = False
    lead_diagnosis_id: str = ""
    lead_diagnosis_name: str = ""
    lead_diagnosis_reasoning: str = ""
    opinions: list[dict[str, Any]] = field(default_factory=list)
    treatment: list[str] = field(default_factory=list)
    steps: int = 0
    transcript: list[dict[str, Any]] = field(default_factory=list)

    def add_transcript(
        self,
        agent: str,
        state: HospitalState,
        action_type: str,
        payload: dict[str, Any],
    ) -> None:
        self.transcript.append(
            {"agent": agent, "state": state.value, "action": action_type, "payload": payload}
        )
