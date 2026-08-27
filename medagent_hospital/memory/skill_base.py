"""Validated, reusable diagnostic skills.

Unlike a case memory, a skill stores an action policy rather than a historical
diagnosis label.  It is only applicable when its complete evidence predicate
is present, and its utility is tracked separately from retrieval frequency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class DiagnosticSkill:
    skill_id: str
    name: str
    trigger: tuple[str, ...]
    favor: str
    against: str
    action: str = "rerank"
    strength: float = 0.25
    trials: int = 0
    successes: int = 0
    harmful: int = 0
    source: str = "reflection"

    @property
    def utility(self) -> float:
        return (self.successes - self.harmful) / self.trials if self.trials else 0.0

    @property
    def success_rate(self) -> float:
        return self.successes / self.trials if self.trials else 0.0


class DiagnosticSkillBase:
    """Small skill library with explicit admission and lifecycle operations."""

    def __init__(self, skills: list[DiagnosticSkill] | None = None) -> None:
        self._skills = list(skills or [])

    def add(self, skill: DiagnosticSkill) -> None:
        if any(existing.skill_id == skill.skill_id for existing in self._skills):
            return
        self._skills.append(skill)

    def get(self, skill_id: str) -> DiagnosticSkill | None:
        return next((skill for skill in self._skills if skill.skill_id == skill_id), None)

    def retrieve(self, query: dict[str, Any] | Any, top_k: int = 3) -> list[DiagnosticSkill]:
        terms = self._terms(query)
        applicable = [skill for skill in self._skills if set(skill.trigger) <= terms]
        applicable.sort(key=lambda skill: (skill.utility, skill.strength), reverse=True)
        return applicable[:top_k]

    def record(self, skill: DiagnosticSkill, correct: bool, changed: bool) -> None:
        if not changed:
            return
        skill.trials += 1
        if correct:
            skill.successes += 1
        else:
            skill.harmful += 1

    def prune(self, min_trials: int = 5, min_utility: float = 0.0) -> int:
        before = len(self._skills)
        self._skills = [
            skill for skill in self._skills
            if skill.trials < min_trials or skill.utility >= min_utility
        ]
        return before - len(self._skills)

    @staticmethod
    def _terms(query: dict[str, Any] | Any) -> set[str]:
        if isinstance(query, dict):
            return (
                set(query.get("symptoms", []))
                | set(query.get("medical_history", []))
                | set(query.get("exam_names", []))
            )
        terms = set(getattr(query, "symptoms", [])) | set(getattr(query, "medical_history", []))
        terms |= {
            exam.name for exam in getattr(query, "exam_results", []) if exam.is_abnormal()
        }
        return terms

    def __iter__(self):
        return iter(self._skills)

    def __len__(self) -> int:
        return len(self._skills)
