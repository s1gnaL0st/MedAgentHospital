"""LangGraph-style orchestration for one patient message turn.

The graph deliberately owns routing only. Existing Agent handlers continue to
own clinical behavior, while this module makes the workflow State explicit and
checkpoint-friendly for a later persistent checkpointer.
"""

from __future__ import annotations

from typing import Any, Callable, TypedDict


class PatientGraphState(TypedDict, total=False):
    session_id: str
    stage: str
    content: str
    response: dict[str, Any]
    next_stage: str


Handler = Callable[[Any, str], dict[str, Any]]


class _FallbackGraph:
    """Small compatibility runner for environments without langgraph installed."""

    def __init__(self, handlers: dict[str, Handler], get_session: Callable[[str], Any]):
        self.handlers = handlers
        self.get_session = get_session

    def invoke(self, state: PatientGraphState, config: dict | None = None) -> PatientGraphState:
        session = self.get_session(state["session_id"])
        stage = session.stage
        handler = self.handlers.get(stage)
        if handler is None:
            raise ValueError(f"患者流程没有可用节点: {stage}")
        return {
            **state,
            "response": handler(session, state["content"]),
            "next_stage": session.stage,
        }


def build_patient_graph(
    *,
    get_session: Callable[[str], Any],
    triage: Handler,
    doctor: Handler,
    chief: Handler,
    checkpointer: Any | None = None,
) -> Any:
    """Build the patient workflow graph with explicit conditional routing."""
    handlers = {"triage": triage, "doctor": doctor, "chief": chief}
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return _FallbackGraph(handlers, get_session)

    graph = StateGraph(PatientGraphState)

    def run_node(stage: str):
        def node(state: PatientGraphState) -> dict[str, Any]:
            session = get_session(state["session_id"])
            return {
                "response": handlers[stage](session, state["content"]),
                "next_stage": session.stage,
            }

        return node

    for stage in handlers:
        graph.add_node(stage, run_node(stage))

    def route(state: PatientGraphState) -> str:
        return state.get("stage", "triage")

    graph.add_conditional_edges(
        START,
        route,
        {"triage": "triage", "doctor": "doctor", "chief": "chief"},
    )
    for stage in handlers:
        graph.add_edge(stage, END)
    return graph.compile(checkpointer=checkpointer)
