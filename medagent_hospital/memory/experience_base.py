"""Experience base: structured reflection rules validated before they survive."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ExperienceRule:
    trigger: tuple[str, ...]
    rule: str
    favor: str = ""
    against: str = ""
    strength: float = 0.6
    validations: int = 0
    successes: int = 0
    source: str = "reflection"
    rule_id: str = ""

    @property
    def survival_rate(self) -> float:
        return self.successes / self.validations if self.validations else 0.0


@dataclass
class RuleHit:
    rule: ExperienceRule
    score: float


class ExperienceBase:
    def __init__(self, rules: list[ExperienceRule] | None = None) -> None:
        self._rules: list[ExperienceRule] = list(rules) if rules else []

    def add(self, rule: ExperienceRule) -> None:
        if not rule.rule_id:
            rule.rule_id = f"R{len(self._rules) + 1}"
        self._rules.append(rule)

    def remove(self, rule: ExperienceRule) -> None:
        self._rules.remove(rule)

    def copy(self) -> "ExperienceBase":
        return ExperienceBase(list(self._rules))

    def get(self, rule_id: str) -> ExperienceRule | None:
        for rule in self._rules:
            if rule.rule_id == rule_id:
                return rule
        return None

    def prune(self, min_survival_rate: float, min_validations: int = 3) -> int:
        """Remove rules that have enough evidence but poor survival."""
        before = len(self._rules)
        self._rules = [
            rule
            for rule in self._rules
            if not (
                rule.validations >= min_validations
                and rule.survival_rate < min_survival_rate
            )
        ]
        return before - len(self._rules)

    def adjust_strengths(self, min_validations: int = 3) -> int:
        """Scale rule strength by survival rate once enough evidence exists."""
        changed = 0
        for rule in self._rules:
            if rule.validations < min_validations:
                continue
            new_strength = 0.6 * (0.5 + rule.survival_rate)
            new_strength = min(max(new_strength, 0.1), 1.0)
            if abs(new_strength - rule.strength) > 1e-6:
                rule.strength = round(new_strength, 3)
                changed += 1
        return changed

    def retrieve(self, query: dict[str, Any] | Any, top_k: int = 4) -> list[RuleHit]:
        query_terms = self._feature_terms(query)
        hits: list[RuleHit] = []
        for rule in self._rules:
            triggers = set(rule.trigger)
            overlap = len(triggers & query_terms)
            if overlap == 0:
                continue
            hits.append(RuleHit(rule=rule, score=overlap / len(triggers)))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]

    @staticmethod
    def _feature_terms(query: dict[str, Any] | Any) -> set[str]:
        if isinstance(query, dict):
            return (
                set(query.get("symptoms", []))
                | set(query.get("medical_history", []))
                | set(query.get("exam_names", []))
            )
        symptoms = query.symptoms if hasattr(query, "symptoms") else []
        history = query.medical_history if hasattr(query, "medical_history") else []
        exam_names = []
        if hasattr(query, "exam_results"):
            exam_names = [exam.name for exam in query.exam_results if exam.is_abnormal()]
        return set(symptoms) | set(history) | set(exam_names)

    def __len__(self) -> int:
        return len(self._rules)

    def __iter__(self):
        return iter(self._rules)
