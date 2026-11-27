"""Crash-log settings read straight from the environment (Task 33).

Stdlib only, and independent of :func:`src.configuration.load_settings`, so a
crash in settings loading (or at import time) can still be recorded. ``.env`` is
loaded best-effort with the same "never clobber the shell" rule as the app.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_RUN_LOG_MAX_MB = 25
DEFAULT_TAIL_LINES = 500


@dataclass
class CrashLogConfig:
    """Where crash bundles/run logs go and what they include."""

    data_dir: Path
    enabled: bool = True
    run_log: bool = True
    include_locals: bool = False
    max_bundles: int = 0
    max_days: int = 0
    run_log_max_bytes: int = DEFAULT_RUN_LOG_MAX_MB * 1024 * 1024

    @property
    def crash_dir(self) -> Path:
        return self.data_dir / "crash_logs"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"


def _bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _load_env_file() -> None:
    with contextlib.suppress(Exception):
        from dotenv import load_dotenv

        path = PROJECT_ROOT / ".env"
        if path.is_file():
            load_dotenv(path, override=False)


def load_crash_config(data_dir: Path | None = None) -> CrashLogConfig:
    """Read ``AUTOJOB_CRASH_LOG_*``; never raises, falls back to ``./data``."""
    _load_env_file()
    if data_dir is None:
        raw = (os.environ.get("AUTOJOB_DATA_DIR") or "").strip()
        data_dir = Path(raw).expanduser() if raw else PROJECT_ROOT / "data"
    max_mb = max(1, _int("AUTOJOB_CRASH_LOG_RUN_LOG_MAX_MB", DEFAULT_RUN_LOG_MAX_MB))
    return CrashLogConfig(
        data_dir=Path(data_dir),
        enabled=_bool("AUTOJOB_CRASH_LOG_ENABLED", True),
        run_log=_bool("AUTOJOB_CRASH_LOG_RUN_LOG", True),
        include_locals=_bool("AUTOJOB_CRASH_LOG_INCLUDE_LOCALS", False),
        max_bundles=max(0, _int("AUTOJOB_CRASH_LOG_MAX_BUNDLES", 0)),
        max_days=max(0, _int("AUTOJOB_CRASH_LOG_MAX_DAYS", 0)),
        run_log_max_bytes=max_mb * 1024 * 1024,
    )


__all__ = ["PROJECT_ROOT", "CrashLogConfig", "load_crash_config"]
