"""Assemble the LinkedIn agent LangGraph state machine.

    START -> ingest -> browse -> match -> fill -> await_submit -> next_job -> match
                                                              |                 |
                                                              +-> cleanup <-----+
                                                                  (stop)
    cleanup -> verify -> END

``browse`` runs the browser steps in one session (Task 1 log in/search/filter,
Task 2 open Easy Apply, Task 3 read the job description) and keeps that session
open. ``match`` selects the best resume offline, ``fill`` fills the still-open
Easy Apply form (Task 4) and, inside it, asks the human in the browser about
unknown questions and remembers their answers (Task 5).

**Task 8:** when Task 4 stops at the terminal step (only **Submit application**
remains) the graph waits for the **human** to submit the application
(``await_submit``; the agent never clicks Submit). On a detected submission it
loops back to ``next_job``, which opens the next unapplied job (Tasks 6-7) and
re-runs ``match``/``fill`` for it — repeating until the jobs-per-run cap is
reached, no unapplied job remains, the human closes the browser, or a step fails.
``cleanup`` then closes the session once. Failure paths skip straight to
``cleanup`` (or ``verify`` for a dry run) so the session is always released.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.nodes import await_submit, browse, cleanup, fill, ingest, match, next_job, verify
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


def _route_after_fill(state: ApplyState) -> str:
    """Wait for the human only when the walk stopped at the terminal step."""
    if state.get("errors"):
        return "cleanup"
    task4 = state.get("task4")
    if task4 is None or not task4.reached_terminal_step or task4.submitted:
        return "cleanup"
    return "await_submit"


def _loop_stopped(state: ApplyState) -> bool:
    """True when Task 8 recorded a reason to stop the submit-and-repeat loop."""
    task8 = state.get("task8")
    return task8 is not None and bool(task8.stopped_reason)


def _route_after_submit(state: ApplyState) -> str:
    """Continue to the next job unless a stop reason was recorded."""
    if state.get("errors") or _loop_stopped(state):
        return "cleanup"
    return "next_job"


def _route_after_next_job(state: ApplyState) -> str:
    """Match a resume for the job ``next_job`` opened, or stop."""
    if state.get("errors") or _loop_stopped(state):
        return "cleanup"
    return "match"


def build_graph():
    """Construct and compile the agent graph."""
    builder = StateGraph(ApplyState)

    builder.add_node("ingest", ingest)
    builder.add_node("browse", browse)
    builder.add_node("match", match)
    builder.add_node("fill", fill)
    builder.add_node("await_submit", await_submit)
    builder.add_node("next_job", next_job)
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
    builder.add_conditional_edges(
        "fill", _route_after_fill, {"await_submit": "await_submit", "cleanup": "cleanup"}
    )
    builder.add_conditional_edges(
        "await_submit", _route_after_submit, {"next_job": "next_job", "cleanup": "cleanup"}
    )
    builder.add_conditional_edges(
        "next_job", _route_after_next_job, {"match": "match", "cleanup": "cleanup"}
    )
    builder.add_edge("cleanup", "verify")
    builder.add_edge("verify", END)

    return builder


# Compiled graph, importable by the LangGraph CLI (see langgraph.json).
graph = build_graph().compile()
