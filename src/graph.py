"""Assemble the Task 1 LangGraph state machine.

    START -> ingest -> browse -> verify -> END

``ingest`` can short-circuit to ``END`` when the URL or query is invalid.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.nodes import browse, ingest, verify
from src.state import ApplyState


def _route_after_ingest(state: ApplyState) -> str:
    return "end" if state.get("status") == "failed" else "browse"


def build_graph():
    """Construct and compile the Task 1 graph."""
    builder = StateGraph(ApplyState)

    builder.add_node("ingest", ingest)
    builder.add_node("browse", browse)
    builder.add_node("verify", verify)

    builder.add_edge(START, "ingest")
    builder.add_conditional_edges("ingest", _route_after_ingest, {"browse": "browse", "end": END})
    builder.add_edge("browse", "verify")
    builder.add_edge("verify", END)

    return builder


# Compiled graph, importable by the LangGraph CLI (see langgraph.json).
graph = build_graph().compile()
