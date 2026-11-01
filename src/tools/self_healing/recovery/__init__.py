"""Self-healing recovery: close/reopen the same job and run the repair command.

Split by concern so each module stays small:

* :mod:`.reopen` -- force-close the failed session and reopen the same job.
* :mod:`.repair` -- run the configured repair/test commands and reload the stack.

This module re-exports the public API, so existing imports such as
``from src.tools.self_healing.recovery import reopen_same_job`` keep working
unchanged.
"""

from __future__ import annotations

from src.tools.self_healing.recovery.reopen import (
    ReopenResult,
    close_run_force,
    job_target_from_state,
    reopen_same_job,
)
from src.tools.self_healing.recovery.repair import (
    _RUNTIME_MODULES,
    CommandFn,
    _run_command,
    reload_runtime_modules,
    run_repair_and_test,
)

__all__ = [
    "CommandFn",
    "ReopenResult",
    "_RUNTIME_MODULES",
    "_run_command",
    "close_run_force",
    "job_target_from_state",
    "reload_runtime_modules",
    "reopen_same_job",
    "run_repair_and_test",
]
