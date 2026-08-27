"""LangGraph patient workflow tests."""

import sqlite3
from types import SimpleNamespace

from langgraph.checkpoint.sqlite import SqliteSaver

from medagent_hospital.web.patient_graph import build_patient_graph


def test_patient_graph_routes_and_persists_thread_state(tmp_path) -> None:
    connection = sqlite3.connect(
        str(tmp_path / "checkpoints.db"), check_same_thread=False
    )
    checkpointer = SqliteSaver(connection)
    checkpointer.setup()
    session = SimpleNamespace(stage="triage")

    def get_session(_session_id: str):
        return session

    def triage(current_session, content: str) -> dict:
        assert content == "我发热咳嗽"
        current_session.stage = "doctor"
        return {"stage": "doctor"}

    def doctor(current_session, _content: str) -> dict:
        current_session.stage = "done"
        return {"stage": "done"}

    def chief(_current_session, _content: str) -> dict:
        raise AssertionError("chief should not run in this route")

    graph = build_patient_graph(
        get_session=get_session,
        triage=triage,
        doctor=doctor,
        chief=chief,
        checkpointer=checkpointer,
    )
    config = {"configurable": {"thread_id": "patient-1"}}
    result = graph.invoke(
        {"session_id": "patient-1", "stage": "triage", "content": "我发热咳嗽"},
        config=config,
    )

    assert result["response"] == {"stage": "doctor"}
    checkpoint = graph.get_state(config)
    assert checkpoint.values["next_stage"] == "doctor"
    assert checkpoint.values["session_id"] == "patient-1"
    connection.close()


def test_patient_graph_coordinator_routes_to_imaging(tmp_path) -> None:
    connection = sqlite3.connect(
        str(tmp_path / "checkpoints-imaging.db"), check_same_thread=False
    )
    checkpointer = SqliteSaver(connection)
    checkpointer.setup()
    session = SimpleNamespace(stage="doctor")

    def get_session(_session_id: str):
        return session

    graph = build_patient_graph(
        get_session=get_session,
        triage=lambda *_: {"stage": "triage"},
        doctor=lambda *_: {"stage": "doctor"},
        chief=lambda *_: {"stage": "chief"},
        imaging=lambda *_: {"stage": "doctor", "report": True},
        coordinate=lambda _session, content: {
            "route": "imaging" if "CT" in content else "doctor",
            "route_reason": "影像资料交给影像 Agent",
        },
        checkpointer=checkpointer,
    )
    result = graph.invoke(
        {"session_id": "patient-imaging", "stage": "doctor", "content": "胸部CT"},
        config={"configurable": {"thread_id": "patient-imaging"}},
    )
    assert result["route"] == "imaging"
    assert result["response"]["report"] is True
    connection.close()
