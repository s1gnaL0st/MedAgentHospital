"""Tests for the structured disease knowledge base."""

from medagent_hospital.knowledge import load_knowledge_base


def test_knowledge_base_loads_and_is_valid() -> None:
    kb = load_knowledge_base()
    assert kb.validate() == []


def test_knowledge_base_scope() -> None:
    kb = load_knowledge_base()
    assert len(kb.diseases) == 48
    assert len(kb.departments) == 6
    assert set(kb.departments) == {
        "心内科",
        "呼吸科",
        "消化科",
        "神经内科",
        "内分泌科",
        "皮肤科",
    }
    for department in kb.departments:
        assert len(kb.by_department(department)) == 8


def test_knowledge_base_lookup() -> None:
    kb = load_knowledge_base()
    herpes_zoster = kb.by_name("带状疱疹")
    assert herpes_zoster is not None
    assert herpes_zoster.department == "皮肤科"
    assert "沿神经分布簇集性水疱" in herpes_zoster.symptoms
    assert kb.get("CARD-001").name == "急性心肌梗死"
    assert kb.by_name("感冒") is not None
