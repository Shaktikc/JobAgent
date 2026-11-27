"""Task 33: a durable crash bundle for every crash, plus a per-run log.

Stdlib-only at import, so the CLI can install it before importing ``src.main``.
Bundles live in ``data/crash_logs/<id>/`` with an append-only ``index.json``; the
run log is ``data/logs/run-<UTC>-<pid>.log``.
"""

from src.tools.crash_logs.hooks import (
    install_asyncio_handler,
    install_crash_logging,
    is_windows_pipe_noise,
    uninstall_crash_logging,
)
from src.tools.crash_logs.log_tee import tee_active
from src.tools.crash_logs.recorder import (
    already_recorded,
    record_crash,
    record_crash_async,
    record_exception,
)
from src.tools.crash_logs.runtime import note_stage, note_state, run_context


def note_line(message: str) -> None:
    """Fallback run-log line from the status reporter when no tee is installed."""
    run_log = run_context().run_log
    if run_log is not None and not tee_active():
        run_log.write_line("status", str(message))


__all__ = [
    "already_recorded",
    "install_asyncio_handler",
    "install_crash_logging",
    "is_windows_pipe_noise",
    "note_line",
    "note_stage",
    "note_state",
    "record_crash",
    "record_crash_async",
    "record_exception",
    "run_context",
    "uninstall_crash_logging",
]
