"""Assemble the LinkedIn agent LangGraph state machine.

    START -> ingest -> browse -> match -> fill -> cleanup -> verify -> END

``browse`` runs the browser steps in one session (Task 1 log in/search/filter,
Task 2 open Easy Apply, Task 3 read the job description) and keeps that session
open. ``match`` selects the best resume offline, ``fill`` fills the still-open
Easy Apply form (Task 4) and, inside it, asks the human in the browser about
unknown questions and remembers their answers (Task 5), and ``cleanup`` closes the
browser. Failure paths skip straight to ``cleanup`` (or ``verify`` for a dry run)
so the session is always released.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.nodes import browse, cleanup, fill, ingest, match, verify
from src.state import ApplyState


def _route_after_ingest(state: ApplyState) -> str:
    return "end" if state.get("status") == "failed" else "browse"


def _route_after_browse(state: ApplyState) -> str:
    """A dry run skips matching; a browser failure skips to cleanup."""
    if state.get("dry_run", True):
        return "verify"
    if state.get("errors"):
        return "cleanup"
    return "match"


def _route_after_match(state: ApplyState) -> str:
    """Only fill the form when resume selection succeeded."""
    return "cleanup" if state.get("errors") else "fill"


def build_graph():
    """Construct and compile the agent graph."""
    builder = StateGraph(ApplyState)

    builder.add_node("ingest", ingest)
    builder.add_node("browse", browse)
    builder.add_node("match", match)
    builder.add_node("fill", fill)
    builder.add_node("cleanup", cleanup)
    builder.add_node("verify", verify)

    builder.add_edge(START, "ingest")
    builder.add_conditional_edges("ingest", _route_after_ingest, {"browse": "browse", "end": END})
    builder.add_conditional_edges(
        "browse",
        _route_after_browse,
        {"match": "match", "cleanup": "cleanup", "verify": "verify"},
    )
    builder.add_conditional_edges(
        "match", _route_after_match, {"fill": "fill", "cleanup": "cleanup"}
    )
    builder.add_edge("fill", "cleanup")
    builder.add_edge("cleanup", "verify")
    builder.add_edge("verify", END)

    return builder


# Compiled graph, importable by the LangGraph CLI (see langgraph.json).
graph = build_graph().compile()
