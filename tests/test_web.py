"""API smoke tests for the demo dashboard."""

import pytest

from medagent_hospital.web.server import (
    _answer_question_assistant,
    _confirm_assistant,
    _kb_overview,
    _message_assistant,
    _patient_message,
    _run_episode,
    _set_reasoner_assistant,
    _start_assistant,
    _start_patient,
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


def test_assistant_reasoner_switch() -> None:
    state = _start_assistant({"symptoms": "发热", "reasoner": "llm"})
    assert state["reasoner"] == "llm"
    state = _set_reasoner_assistant(
        {"session_id": state["session_id"], "reasoner": "rule"}
    )
    assert state["reasoner"] == "rule"
    with pytest.raises(ValueError):
        _set_reasoner_assistant(
            {"session_id": state["session_id"], "reasoner": "gpt"}
        )


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


def test_assistant_imaging_report_generated() -> None:
    from medagent_hospital.web.server import STATE

    state = _start_assistant(
        {"gender": "male", "age": 60, "symptoms": "喘息,胸闷,咳嗽"}
    )
    session_id = state["session_id"]
    state = _confirm_assistant(
        {"session_id": session_id, "stage": "guide", "accepted": True}
    )
    while state["stage"] == "doctor" and state["suggestion"].get("question"):
        state = _answer_question_assistant(
            {
                "session_id": session_id,
                "symptom": state["suggestion"]["question"],
                "present": True,
            }
        )
    state = _confirm_assistant(
        {
            "session_id": session_id,
            "stage": "doctor",
            "accepted": True,
            "exams": ["胸部CT"],
            "medications": [],
        }
    )
    assert state["done"] is True
    assert state["reports"]
    reports = STATE.hospital_store.list_reports(session_id)
    assert any(report["exam_name"] == "胸部CT" for report in reports)
    assert all(report["impression"] for report in reports)


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


def test_patient_flow_triage_to_done() -> None:
    state = _start_patient({"gender": "male", "age": 50, "reasoner": "rule"})
    session_id = state["session_id"]
    assert state["current_agent"] == "guide"

    state = _patient_message(
        {"session_id": session_id, "content": "发热,咳嗽,胸痛"}
    )
    assert state["stage"] == "triage"
    assert state["suggestion"]["department"]

    state = _patient_message({"session_id": session_id, "content": "同意"})
    assert state["stage"] == "doctor"
    assert state["current_agent"] == "doctor"
    assert state["handoffs"][0]["to"] == "doctor"

    while state["suggestion"] and state["suggestion"].get("question"):
        state = _patient_message({"session_id": session_id, "content": "有"})
    assert state["suggestion"]["candidates"]

    state = _patient_message({"session_id": session_id, "content": "确认"})
    assert state["done"] is True
    assert state["orders"]


def test_patient_escalate_to_chief() -> None:
    state = _start_patient({"gender": "male", "age": 60})
    session_id = state["session_id"]
    state = _patient_message(
        {"session_id": session_id, "content": "喘息,胸闷,咳嗽"}
    )
    state = _patient_message({"session_id": session_id, "content": "同意"})
    while state["suggestion"] and state["suggestion"].get("question"):
        state = _patient_message({"session_id": session_id, "content": "有"})

    state = _patient_message({"session_id": session_id, "content": "请主任会诊"})
    assert state["stage"] == "chief"
    assert state["current_agent"] == "chief"
    assert state["handoffs"][-1]["to"] == "chief"

    state = _patient_message({"session_id": session_id, "content": "确认"})
    assert state["done"] is True
