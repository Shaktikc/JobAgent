"""Self-healing Easy Apply loop (Task 11).

Public API:

- :class:`~src.tools.self_healing.models.SelfHealingOutcome` — graph-state summary.
- :func:`~src.tools.self_healing.loop.heal_fill_failure` — the bounded loop.
- :func:`~src.tools.self_healing.capture.capture_failure` — evidence bundle.
- :func:`~src.tools.self_healing.buglog.record_failure` — bug-log entry.
- :func:`~src.tools.self_healing.recovery.close_run_force` /
  :func:`~src.tools.self_healing.recovery.reopen_same_job` — browser lifecycle.

The package is intentionally lazy: importing it must not require the optional
``browser`` extra. Only :mod:`models` and :mod:`fingerprint` are safe to import at
graph-state load time.
"""

from __future__ import annotations

from src.tools.self_healing.models import (
    CapturedFailure,
    FailureEvidence,
    FailureRecord,
    HealingAttempt,
    JobTarget,
    SelfHealingOutcome,
)

__all__ = [
    "CapturedFailure",
    "FailureEvidence",
    "FailureRecord",
    "HealingAttempt",
    "JobTarget",
    "SelfHealingOutcome",
    "capture_failure",
    "close_run_force",
    "heal_fill_failure",
    "job_target_from_state",
    "record_failure",
    "reopen_same_job",
    "update_bug",
]


def __getattr__(name: str):
    """Import the browser-facing helpers only when a caller asks for them."""
    if name == "capture_failure":
        from src.tools.self_healing.capture import capture_failure

        return capture_failure
    if name in {"close_run_force", "reopen_same_job"}:
        from src.tools.self_healing.recovery import close_run_force, reopen_same_job

        return {"close_run_force": close_run_force, "reopen_same_job": reopen_same_job}[name]
    if name in {"record_failure", "update_bug"}:
        from src.tools.self_healing.buglog import record_failure, update_bug

        return {"record_failure": record_failure, "update_bug": update_bug}[name]
    if name in {"heal_fill_failure", "job_target_from_state"}:
        from src.tools.self_healing.loop import heal_fill_failure, job_target_from_state

        return {
            "heal_fill_failure": heal_fill_failure,
            "job_target_from_state": job_target_from_state,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
