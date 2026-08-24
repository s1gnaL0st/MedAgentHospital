"""Database management agent tests: audit, isolation, retrieval and reflection."""

import pytest

from medagent_hospital.knowledge import load_knowledge_base
from medagent_hospital.memory.case_base import MedicalCase
from medagent_hospital.memory.experience_base import ExperienceRule
from medagent_hospital.simulacrum.memory_manager import MemoryManager
from medagent_hospital.web.db_agent import DatabaseAgent
from medagent_hospital.web.hospital_store import HospitalRecordStore


@pytest.fixture
def db_agent(tmp_path):
    store = HospitalRecordStore(tmp_path / "test.db")
    kb = load_knowledge_base()
    return DatabaseAgent(store, kb), store


def test_memory_save_rejected_on_isolation(db_agent) -> None:
    agent, store = db_agent
    store.create_session("S1", {"id": "P1"})
    event_id = agent.record_event(
        "S1",
        1,
        "doctor",
        "diagnosis",
        {"diagnosis": "肺炎"},
        ["doctor-001", "db-agent"],
    )
    result = agent.save_memory(
        "guide-001",
        "S1",
        "summary",
        {"department": "呼吸科"},
        source_event_id=event_id,
    )
    assert result["verdict"] == "rejected"
    assert any("可见范围" in issue for issue in result["issues"])


def test_memory_save_approved_and_retrieved(db_agent) -> None:
    agent, store = db_agent
    store.create_session("S2", {"id": "P2"})
    result = agent.save_memory(
        "doctor-001",
        "S2",
        "case",
        {
            "diagnosis_id": "RESP-001",
            "diagnosis_name": "社区获得性肺炎",
            "symptoms": ["发热", "咳嗽"],
        },
        visible_to=["doctor-001"],
    )
    assert result["verdict"] == "approved"
    hits = agent.retrieve("doctor-001", {"symptoms": ["发热", "咳嗽"]})
    assert hits and hits[0]["memory"]["memory_type"] == "case"
    hits2 = agent.retrieve("doctor-001", {"symptoms": ["发热", "咳嗽"]})
    assert hits2[0]["score"] > hits[0]["score"]


def test_memory_save_rejected_invalid_disease(db_agent) -> None:
    agent, store = db_agent
    store.create_session("S3", {"id": "P3"})
    result = agent.save_memory(
        "doctor-001",
        "S3",
        "case",
        {"diagnosis_id": "NOPE-001"},
        visible_to=["doctor-001"],
    )
    assert result["verdict"] == "rejected"
    assert any("disease_id" in issue for issue in result["issues"])


def test_reflect_creates_reflection_memory(db_agent) -> None:
    agent, store = db_agent
    store.create_session("S4", {"id": "P4"})
    agent.save_memory(
        "doctor-001",
        "S4",
        "case",
        {"diagnosis_name": "肺炎"},
        visible_to=["doctor-001"],
    )
    agent.save_memory(
        "doctor-001",
        "S4",
        "rule",
        {"rule": "发热咳嗽考虑肺炎"},
        visible_to=["doctor-001"],
    )
    result = agent.reflect("doctor-001", "S4")
    assert result["verdict"] == "approved"
    memories = store.list_memories("doctor-001")
    assert any(memory["memory_type"] == "reflection" for memory in memories)


def test_training_memories_survive_database_reopen(tmp_path) -> None:
    db_path = tmp_path / "training.db"
    kb = load_knowledge_base()
    store = HospitalRecordStore(db_path)
    agent = DatabaseAgent(store, kb)
    manager = MemoryManager(
        kb,
        db_agent=agent,
        memory_agent_id="doctor-training-01",
        memory_session_id="training-D-42",
        department="呼吸科",
    )
    manager.case_base.add(
        MedicalCase(
            patient={"symptoms": ["发热"], "exam_names": ["胸部CT"]},
            diagnosis="社区获得性肺炎",
            diagnosis_id="RESP-001",
            treatment="抗生素",
        )
    )
    manager.experience_base.add(
        ExperienceRule(
            trigger=("发热", "胸部CT"),
            rule="发热伴胸部CT异常优先考虑肺炎",
            favor="RESP-001",
        )
    )
    manager.persist_all()
    store.close()

    reopened = HospitalRecordStore(db_path)
    reopened_agent = DatabaseAgent(reopened, kb)
    restored_manager = MemoryManager(
        kb,
        db_agent=reopened_agent,
        memory_agent_id="doctor-training-01",
        memory_session_id="training-D-42",
        department="呼吸科",
    )
    restored_manager.load_persisted()

    assert len(restored_manager.case_base) == 1
    assert restored_manager.case_base._cases[0].diagnosis_id == "RESP-001"
    assert len(restored_manager.experience_base) == 1
    assert restored_manager.experience_base.get("R1").favor == "RESP-001"
    reopened.close()
