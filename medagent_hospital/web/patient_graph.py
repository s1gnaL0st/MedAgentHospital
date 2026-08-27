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
    route: str
    route_reason: str
    structured_state: dict[str, Any]
    response: dict[str, Any]
    next_stage: str


Handler = Callable[[Any, str], dict[str, Any]]


class _FallbackGraph:
    """Small compatibility runner for environments without langgraph installed."""

    def __init__(
        self,
        handlers: dict[str, Handler],
        get_session: Callable[[str], Any],
        coordinate: Callable[[Any, str], dict[str, str]] | None = None,
    ):
        self.handlers = handlers
        self.get_session = get_session
        self.coordinate = coordinate

    def invoke(self, state: PatientGraphState, config: dict | None = None) -> PatientGraphState:
        session = self.get_session(state["session_id"])
        decision = self.coordinate(session, state["content"]) if self.coordinate else {
            "route": session.stage,
            "route_reason": "按当前阶段路由",
        }
        stage = decision["route"]
        handler = self.handlers.get(stage)
        if handler is None:
            raise ValueError(f"患者流程没有可用节点: {stage}")
        return {
            **state,
            **decision,
            "response": handler(session, state["content"]),
            "next_stage": session.stage,
        }


def build_patient_graph(
    *,
    get_session: Callable[[str], Any],
    triage: Handler,
    doctor: Handler,
    chief: Handler,
    guide: Handler | None = None,
    nurse: Handler | None = None,
    imaging: Handler | None = None,
    coordinate: Callable[[Any, str], dict[str, str]] | None = None,
    checkpointer: Any | None = None,
) -> Any:
    """Build the patient workflow graph with explicit conditional routing."""
    handlers = {"triage": triage, "doctor": doctor, "chief": chief}
    if guide is not None:
        handlers["guide"] = guide
    if nurse is not None:
        handlers["nurse"] = nurse
    if imaging is not None:
        handlers["imaging"] = imaging
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return _FallbackGraph(handlers, get_session, coordinate)

    graph = StateGraph(PatientGraphState)

    def coordinator_node(state: PatientGraphState) -> dict[str, Any]:
        session = get_session(state["session_id"])
        if coordinate is None:
            return {"route": state.get("stage", "triage"), "route_reason": "按当前阶段路由"}
        return coordinate(session, state["content"])

    def run_node(stage: str):
        def node(state: PatientGraphState) -> dict[str, Any]:
            session = get_session(state["session_id"])
            return {
                "response": handlers[stage](session, state["content"]),
                "next_stage": session.stage,
            }

        return node

    graph.add_node("coordinator", coordinator_node)
    for stage in handlers:
        graph.add_node(stage, run_node(stage))

    def route(state: PatientGraphState) -> str:
        return state.get("route", "triage")

    graph.add_conditional_edges(
        START,
        lambda _state: "coordinator",
        {"coordinator": "coordinator"},
    )
    graph.add_conditional_edges(
        "coordinator",
        route,
        {stage: stage for stage in handlers},
    )
    for stage in handlers:
        graph.add_edge(stage, END)
    return graph.compile(checkpointer=checkpointer)
