"""Task 33 crash logging for the CLI run: stream the graph, record failures.

``stream_graph`` runs the graph with ``astream(stream_mode="values")`` so every
yielded state is remembered; it returns the final state exactly like
``ainvoke``. A crash or Ctrl+C inside the run is recorded while the event loop
(and so the browser page) is still alive, then re-raised unchanged.
"""

from __future__ import annotations

import asyncio

from src.state import ApplyState
from src.tools.crash_logs import (
    install_asyncio_handler,
    note_state,
    record_crash,
    record_crash_async,
    run_context,
)

_FAILED_STATUSES = {"failed", "needs_review"}


async def stream_graph(graph, state: ApplyState, config: dict) -> ApplyState:
    """Run ``graph`` and return its final state, recording any crash."""
    install_asyncio_handler()
    final: ApplyState = state
    note_state(state)
    try:
        async for value in graph.astream(state, config=config, stream_mode="values"):
            final = value
            note_state(value)
    except asyncio.CancelledError as exc:
        # asyncio.run turns Ctrl+C into a cancellation of the main task.
        await asyncio.wait_for(
            record_crash_async(
                "interrupted", exc=exc, exit_code=130, message="run interrupted (Ctrl+C)"
            ),
            timeout=15,
        )
        raise
    except Exception as exc:
        await record_crash_async("uncaught_exception", exc=exc, exit_code=1)
        raise
    return final


def _login_gate(state: ApplyState) -> bool:
    """The human login gate is a deliberate stop, not a crash."""
    errors = " ".join(str(error) for error in state.get("errors") or []).lower()
    return "login not completed" in errors


def _task_outcome(state: ApplyState) -> dict:
    task8 = state.get("task8")
    healing = state.get("self_healing")
    return {
        "status": state.get("status", ""),
        "task8_stopped_reason": getattr(task8, "stopped_reason", "") if task8 else "",
        "last_submission_status": (
            getattr(task8, "last_submission_status", "") if task8 else ""
        ),
        "self_healing_stop": getattr(healing, "stop_reason", "") if healing else "",
    }


def record_returned_failure(state: ApplyState, exit_code: int) -> str | None:
    """Write a ``returned_failure`` bundle for a failed/needs-review final state.

    Skipped when this run already wrote a bundle (the node/submission guard
    recorded the same event) and for the human login gate.
    """
    if state.get("status") not in _FAILED_STATUSES:
        return None
    if run_context().bundles or _login_gate(state):
        return None
    errors = [str(error) for error in state.get("errors") or []]
    log = [str(entry) for entry in state.get("log") or []]
    message = errors[0] if errors else (log[-1] if log else f"status={state.get('status')}")
    return record_crash(
        "returned_failure",
        state=dict(state),
        exit_code=exit_code,
        message=message,
        extra={"task_outcome": _task_outcome(state)},
    )


def record_cli_failure(kind: str, exc: BaseException, exit_code: int) -> None:
    """Record a caught startup/CLI failure; the caller keeps its message/exit code."""
    record_crash(kind, exc=exc, exit_code=exit_code)


__all__ = ["record_cli_failure", "record_returned_failure", "stream_graph"]
