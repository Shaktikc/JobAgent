"""Task 33: write one terminal crash bundle when self-healing cannot recover.

A recovered crash writes nothing here (the self-healing bundle is the record).
When self-healing already captured the page, the crash bundle links that bundle
and bug id instead of taking a second screenshot/DOM.
"""

from __future__ import annotations

from src.state import ApplyState
from src.tools.crash_logs import note_state, record_crash_async
from src.tools.self_healing.models import SelfHealingOutcome


async def record_node_crash(
    stage: str,
    working: ApplyState,
    result: ApplyState,
    outcome: SelfHealingOutcome,
    *,
    exc: BaseException | None,
    error: str,
    traceback_text: str,
    extra: dict | None = None,
) -> None:
    """Record the unrecovered crash of ``stage``; never raises."""
    latest = {**working, **result}
    latest["log"] = list(working.get("log") or []) + list(result.get("log") or [])
    note_state(latest, stage)
    context = {"stop_reason": outcome.stop_reason, **(extra or {})}
    await record_crash_async(
        "node_crash",
        exc=exc,
        stage=stage,
        state=latest,
        message=error,
        traceback_text=traceback_text,
        extra=context,
        # Self-healing already captured the failed page before closing it.
        capture_page=not outcome.last_bundle,
    )


def remember_recovered(stage: str, working: ApplyState, merged: ApplyState) -> None:
    """Keep the recovered state as the latest, so a later crash sees it (no bundle)."""
    note_state({**working, **merged}, stage)


__all__ = ["record_node_crash", "remember_recovered"]
