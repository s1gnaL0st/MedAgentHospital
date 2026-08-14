"""API smoke tests for the demo dashboard."""

import pytest

from medagent_hospital.web.server import (
    _answer_assistant,
    _confirm_assistant,
    _kb_overview,
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


def test_assistant_full_flow_to_done() -> None:
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
    while state["stage"] == "nurse":
        question = state["suggestion"]["question"]
        state = _answer_assistant(
            {"session_id": session_id, "symptom": question, "present": True}
        )
    assert state["stage"] == "doctor"
    assert state["suggestion"]["candidates"]

    state = _confirm_assistant(
        {"session_id": session_id, "stage": "doctor", "accepted": True}
    )
    assert state["stage"] == "chief"
    assert state["decisions"]["doctor"]["disease_id"]

    state = _confirm_assistant(
        {"session_id": session_id, "stage": "chief", "accepted": True}
    )
    assert state["done"] is True


def test_assistant_rejects_wrong_stage() -> None:
    state = _start_assistant({"symptoms": "发热"})
    with pytest.raises(ValueError):
        _confirm_assistant(
            {"session_id": state["session_id"], "stage": "doctor", "accepted": True}
        )
