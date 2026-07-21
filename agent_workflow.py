"""Optional LangGraph approval gate for Equilibrium's external actions.

This module intentionally does not contact a model, counsellor, or device. It
only provides a durable human-approval boundary for a future deployment where a
student asks the app to perform an external action.
"""
from __future__ import annotations

from typing import TypedDict


class SupportActionState(TypedDict):
    action: str
    destination: str
    student_approved: bool
    result: str


def build_support_approval_graph():
    """Create a graph that cannot execute an action until the student approves it.

    Install the optional dependency first: ``pip install langgraph``. The graph
    is deliberately not wired into ``server.py`` by default, so it cannot alter
    any existing Equilibrium flow.
    """
    try:
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import interrupt
    except ImportError as error:
        raise RuntimeError("LangGraph is optional. Install it with: pip install langgraph") from error

    def request_student_approval(state: SupportActionState) -> dict[str, object]:
        decision = interrupt({
            "kind": "external_action_review",
            "action": state["action"],
            "destination": state["destination"],
            "message": "Nothing will be sent or shared unless the student approves this exact action.",
            "allowed_decisions": ["approve", "reject"],
        })
        return {"student_approved": decision == "approve"}

    def finalise(state: SupportActionState) -> dict[str, str]:
        if not state["student_approved"]:
            return {"result": "No action taken. The student declined."}
        return {"result": "Approved by the student; ready for a narrowly scoped adapter."}

    graph = StateGraph(SupportActionState)
    graph.add_node("request_student_approval", request_student_approval)
    graph.add_node("finalise", finalise)
    graph.add_edge(START, "request_student_approval")
    graph.add_edge("request_student_approval", "finalise")
    graph.add_edge("finalise", END)
    # In-memory checkpoints make the local prototype resumable. Replace this
    # with a reviewed Postgres checkpointer before deployment; do not persist
    # reflection text or behavioural data in graph state.
    return graph.compile(checkpointer=InMemorySaver())
