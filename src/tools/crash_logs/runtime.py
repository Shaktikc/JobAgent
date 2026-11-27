"""Per-process run context for crash logging (Task 33).

Holds the start time, argv, latest graph state and stage, the run log, and the
dedupe markers that guarantee one terminal bundle per crash. It is process-local
and is never written into the graph state.
"""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.tools.crash_logs.config import CrashLogConfig


@dataclass
class RunContext:
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    argv: list[str] = field(default_factory=lambda: list(sys.argv))
    pid: int = field(default_factory=os.getpid)
    config: CrashLogConfig | None = None
    run_log: Any = None  # log_tee.RunLog
    state: dict | None = None
    stage: str = ""
    installed: bool = False
    # Dedupe keys of crashes already written, and exception objects already seen.
    recorded_keys: set[str] = field(default_factory=set)
    recorded_exc_ids: set[int] = field(default_factory=set)
    bundles: list[str] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)


_CONTEXT = RunContext()


def run_context() -> RunContext:
    """The process-wide crash-log context."""
    return _CONTEXT


def reset_run_context(**overrides) -> RunContext:
    """Start a fresh context (CLI start and tests)."""
    global _CONTEXT
    _CONTEXT = RunContext(**overrides)
    return _CONTEXT


def note_state(state: Any, stage: str | None = None) -> None:
    """Remember the latest graph state/stage; never raises."""
    try:
        context = _CONTEXT
        if isinstance(state, dict):
            context.state = dict(state)
        if stage:
            context.stage = stage
    except Exception:  # noqa: BLE001 - evidence only
        pass


def note_stage(stage: str) -> None:
    note_state(None, stage)


__all__ = ["RunContext", "note_stage", "note_state", "reset_run_context", "run_context"]
