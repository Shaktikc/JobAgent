"""Assemble the LinkedIn agent LangGraph state machine.

    START -> ingest -> browse -> match -> open_form -> fill -> await_submit
                                      |                    |             |
                                      +-> next_job <-------+             |
                                      |     ^                           |
                                      |     +---------------------------+
                                      +-> cleanup <---------------------+
    cleanup -> verify -> END

``browse`` runs the browser steps in one session (Task 1 log in/search/filter,
Task 2 select the job and read its description **without** clicking Easy Apply,
Task 3 read the description) and keeps that session open. ``match`` selects the
best resume offline. Only when a resume was selected does ``open_form`` click
Easy Apply; ``fill`` then fills that form (Task 4) and, inside it, asks the human
in the browser about unknown questions and remembers their answers (Task 5).

**Task 8:** when Task 4 stops at the terminal step (only **Submit application**
remains) the graph waits for the **human** to submit the application
(``await_submit``; the agent never clicks Submit). On a detected submission it
loops back to ``next_job``, which opens the next unapplied job (Tasks 6-7) and
re-runs ``match``/``fill`` for it — repeating until the jobs-per-run cap is
reached, no unapplied job remains, the human closes the browser, or a step fails.
``cleanup`` then closes the session once. Failure paths skip straight to
``cleanup`` (or ``verify`` for a dry run) so the session is always released.

**Task 16:** in strict resume-matching mode a job whose description matches no
existing resume is skipped cleanly: ``match`` returns ``status="skipped"``, the
graph goes straight to ``next_job`` (never ``open_form``/``fill``), and the
skipped title is excluded from later passes until no job (or the skip cap) stops
the loop. Because matching happens before the click, a skipped job never opens
the Easy Apply form at all.

Every node is also wrapped by the self-healing guards: uncaught crashes in any
node are recorded/repaired/retried, and returned Task 1-3 hard stops (login gate
excluded) are retried through the task-level guard. Clean Task 8 stops (cap,
timeout, human closed, nothing left) are never treated as crashes.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.nodes import (
    await_submit,
    browse,
    cleanup,
    fill,
    ingest,
    match,
    next_job,
    open_form,
    verify,
)
from src.nodes.self_heal_guard import guard_node
from src.nodes.task_self_heal import guard_task_node
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
    """Open the form only on a selected resume; Task 16 skips go to the next job."""
    if state.get("errors"):
        return "cleanup"
    if state.get("status") == "skipped":
        return "next_job"
    return "open_form"


def _route_after_open_form(state: ApplyState) -> str:
    """Fill the form that was opened for the selected resume."""
    if state.get("errors"):
        return "cleanup"
    return "fill"


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

    # Every node that can raise is guarded: an uncaught crash is recorded,
    # repaired/tested, and the same node is retried in a fresh browser instead of
    # silently ending the run (Task 11). ``cleanup`` stays unguarded so a release
    # failure can never relaunch the browser.
    builder.add_node("ingest", guard_node("ingest", ingest, reopen=None))
    # Tasks 1-3 return their failures as outcomes rather than raising, so these
    # two nodes also use the task-level guard (BUG-065).
    builder.add_node("browse", guard_task_node("browse", browse, reopen=None))
    builder.add_node("match", guard_task_node("match", match, reopen="job"))
    # Task 16: the form is clicked only after a resume was selected. A returned
    # form-open failure is retryable through the same-job reopen path.
    builder.add_node("open_form", guard_task_node("open_form", open_form, reopen="job"))
    builder.add_node("fill", guard_node("fill", fill, reopen="job"))
    builder.add_node("await_submit", guard_node("await_submit", await_submit, reopen="job"))
    builder.add_node("next_job", guard_task_node("next_job", next_job, reopen="results"))
    builder.add_node("cleanup", cleanup)
    builder.add_node("verify", guard_node("verify", verify, reopen=None))

    builder.add_edge(START, "ingest")
    builder.add_conditional_edges("ingest", _route_after_ingest, {"browse": "browse", "end": END})
    builder.add_conditional_edges(
        "browse",
        _route_after_browse,
        {"match": "match", "cleanup": "cleanup", "verify": "verify"},
    )
    builder.add_conditional_edges(
        "match",
        _route_after_match,
        {"open_form": "open_form", "next_job": "next_job", "cleanup": "cleanup"},
    )
    builder.add_conditional_edges(
        "open_form",
        _route_after_open_form,
        {"fill": "fill", "cleanup": "cleanup"},
    )
    builder.add_conditional_edges(
        "fill",
        _route_after_fill,
        {"await_submit": "await_submit", "cleanup": "cleanup"},
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
