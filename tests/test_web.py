"""API smoke tests for the demo dashboard."""

import pytest

from medagent_hospital.web.server import (
    _answer_question_assistant,
    _confirm_assistant,
    _kb_overview,
    _message_assistant,
    _run_episode,
    _start_assistant,
)


def test_kb_overview() -> None:
    overview = _kb_overview()
    assert overview["total_diseases"] == 48
    assert len(overview["departments"]) == 6
    assert all(item["disease_count"] == 8 for item in overview["departments"])


def test_run_episode() -> None:
    result = _run_episode(
        {"department": "皮肤科", "disease_id": "DERM-001", "seed": 1}
    )
    assert result["transcript"]
    assert result["diagnosis"]["disease_id"] == "DERM-001"
    assert result["correct"] is True
    assert result["patient"]["symptoms"]


def test_assistant_start_returns_triage() -> None:
    state = _start_assistant(
        {"gender": "male", "age": 50, "symptoms": "发热,咳嗽,胸痛"}
    )
    assert state["stage"] == "guide"
    assert state["suggestion"]["department"]
    assert state["suggestion"]["departments"]
    assert state["patient"]["symptoms"] == ["发热", "咳嗽", "胸痛"]
    assert set(state["role_messages"]) == {"guide", "doctor", "chief"}


def test_assistant_discussion_returns_agent_reply() -> None:
    state = _start_assistant(
        {"gender": "male", "age": 50, "symptoms": "发热,咳嗽"}
    )
    state = _message_assistant(
        {
            "session_id": state["session_id"],
            "role": "guide",
            "content": "为什么不是呼吸科？",
        }
    )
    guide_messages = state["role_messages"]["guide"]
    assert guide_messages[-1]["sender"] == "guide"
    assert "呼吸科" in guide_messages[-1]["content"]


def test_assistant_doctor_flow_persists_orders() -> None:
    from medagent_hospital.web.server import STATE

    state = _start_assistant(
        {
            "gender": "male",
            "age": 60,
            "symptoms": "喘息,胸闷,咳嗽",
            "medical_history": "吸烟",
        }
    )
    session_id = state["session_id"]
    state = _confirm_assistant(
        {"session_id": session_id, "stage": "guide", "accepted": True}
    )
    while state["stage"] == "doctor" and state["suggestion"].get("question"):
        question = state["suggestion"]["question"]
        state = _answer_question_assistant(
            {"session_id": session_id, "symptom": question, "present": True}
        )
    assert state["stage"] == "doctor"
    assert state["suggestion"]["candidates"]

    state = _confirm_assistant(
        {
            "session_id": session_id,
            "stage": "doctor",
            "accepted": True,
            "exams": state["suggestion"]["exams"][:2],
            "medications": state["suggestion"]["treatment"][:2],
        }
    )
    assert state["done"] is True
    assert state["orders"]
    saved = STATE.hospital_store.get_session(session_id)
    assert saved["diagnosis_id"]
    assert saved["completed_at"] is not None


def test_assistant_escalation_to_chief() -> None:
    state = _start_assistant(
        {"gender": "male", "age": 60, "symptoms": "喘息,胸闷,咳嗽"}
    )
    session_id = state["session_id"]
    state = _confirm_assistant(
        {"session_id": session_id, "stage": "guide", "accepted": True}
    )
    state = _confirm_assistant(
        {"session_id": session_id, "stage": "doctor", "escalate": True}
    )
    assert state["stage"] == "chief"
    assert state["suggestion"]["history"]
    assert state["suggestion"]["candidates"]
    state = _confirm_assistant(
        {
            "session_id": session_id,
            "stage": "chief",
            "accepted": True,
            "override": state["suggestion"]["best_id"],
            "exams": state["suggestion"]["exams"][:1],
            "medications": state["suggestion"]["treatment"][:1],
        }
    )
    assert state["done"] is True
    assert state["orders"]


def test_assistant_rejects_wrong_stage() -> None:
    state = _start_assistant({"symptoms": "发热"})
    with pytest.raises(ValueError):
        _confirm_assistant(
            {"session_id": state["session_id"], "stage": "doctor", "accepted": True}
        )
