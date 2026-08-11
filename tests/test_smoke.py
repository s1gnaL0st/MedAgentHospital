"""Smoke tests for the project skeleton."""

from medagent_hospital.config import Settings
from medagent_hospital.memory.case_base import MedicalCase, MedicalCaseBase
from medagent_hospital.memory.experience_base import ExperienceBase, ExperienceRule


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.llm_backend == "rule"
    assert settings.seed == 42


def test_case_base_retrieval() -> None:
    base = MedicalCaseBase()
    base.add(
        MedicalCase(
            patient={"symptoms": ["发热", "干咳"]},
            diagnosis="COVID-19",
            treatment="对症支持治疗",
        )
    )
    hits = base.retrieve({"symptoms": ["发热", "干咳", "乏力"]})
    assert len(hits) == 1
    assert hits[0].case.diagnosis == "COVID-19"


def test_experience_rule_survival_rate() -> None:
    base = ExperienceBase()
    rule = ExperienceRule(trigger=("发热",), rule="发热伴干咳优先考虑呼吸道感染")
    rule.validations = 4
    rule.successes = 3
    base.add(rule)
    hits = base.retrieve({"symptoms": ["发热"]})
    assert hits and hits[0].rule is rule
    assert rule.survival_rate == 0.75
