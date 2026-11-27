"""Durable per-run log file plus an in-memory tail (Task 33).

:class:`RunLog` writes timestamped ``out``/``err`` lines to
``data/logs/run-<UTC>-<pid>.log`` and keeps the last lines in a bounded deque.
:class:`TeeStream` wraps ``sys.stdout``/``sys.stderr`` so every terminal line is
mirrored there while the original stream keeps its behaviour (``isatty``,
``fileno``, ``encoding``… all delegate).
"""

from __future__ import annotations

import os
import sys
import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from src.tools.crash_logs.config import DEFAULT_TAIL_LINES, CrashLogConfig


class RunLog:
    """One run's durable log file and its recent-lines buffer."""

    def __init__(
        self,
        path: Path | None,
        *,
        max_bytes: int = 25 * 1024 * 1024,
        tail: int = DEFAULT_TAIL_LINES,
    ) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.total_lines = 0
        self.truncated = False
        self.error = ""
        self._tail: deque[str] = deque(maxlen=tail)
        self._size = 0
        self._lock = threading.Lock()
        self._file = None
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                self._file = open(path, "a", encoding="utf-8", errors="replace")  # noqa: SIM115
            except OSError as exc:
                self.error = f"run log file unavailable: {exc}"
                self._file = None

    def write_line(self, tag: str, text: str) -> None:
        """Record one line; never raises."""
        try:
            stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            line = f"{stamp} [{tag}] {text.rstrip(chr(10)).rstrip(chr(13))}"
            with self._lock:
                self.total_lines += 1
                self._tail.append(line)
                self._write_file(line)
        except Exception:  # noqa: BLE001 - logging must never break the app
            pass

    def _write_file(self, line: str) -> None:
        if self._file is None or self.truncated:
            return
        data = line + "\n"
        size = len(data.encode("utf-8", errors="replace"))
        if self._size + size > self.max_bytes:
            self.truncated = True
            self._file.write(
                f"[run log truncated at {self.max_bytes} bytes; later lines are kept "
                "only in each crash bundle's run.log tail]\n"
            )
            self._file.flush()
            return
        self._file.write(data)
        self._file.flush()
        self._size += size

    def tail_lines(self) -> list[str]:
        with self._lock:
            return list(self._tail)

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                try:
                    self._file.close()
                except Exception:  # noqa: BLE001
                    pass
                self._file = None


class TeeStream:
    """Mirror a text stream into a :class:`RunLog`, delegating everything else."""

    def __init__(self, original, run_log: RunLog, tag: str) -> None:
        self._original = original
        self._run_log = run_log
        self._tag = tag
        self._partial = ""

    def write(self, text):
        result = self._original.write(text)
        try:
            data = self._partial + str(text)
            *lines, self._partial = data.split("\n")
            for line in lines:
                self._run_log.write_line(self._tag, line)
        except Exception:  # noqa: BLE001
            pass
        return result

    def writelines(self, lines) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        self._original.flush()

    def drain(self) -> None:
        """Record a pending partial line (at shutdown/crash time)."""
        if self._partial:
            self._run_log.write_line(self._tag, self._partial)
            self._partial = ""

    def isatty(self) -> bool:
        return self._original.isatty()

    def fileno(self) -> int:
        return self._original.fileno()

    def __getattr__(self, name):
        return getattr(self._original, name)


def running_under_pytest() -> bool:
    return "pytest" in sys.modules or bool(os.environ.get("PYTEST_CURRENT_TEST"))


def run_log_path(config: CrashLogConfig, started_at: datetime, pid: int) -> Path:
    return config.logs_dir / f"run-{started_at.strftime('%Y%m%d-%H%M%S')}-{pid}.log"


def open_run_log(config: CrashLogConfig, started_at: datetime, pid: int) -> RunLog:
    """Open the run log file (memory-only when disabled or unavailable)."""
    path = run_log_path(config, started_at, pid) if config.run_log else None
    run_log = RunLog(path, max_bytes=config.run_log_max_bytes)
    if path is not None and run_log.error == "":
        run_log.write_line("meta", f"run log started pid={pid} argv={sys.argv!r}")
    return run_log


def install_tee(run_log: RunLog, *, force: bool = False) -> bool:
    """Wrap ``sys.stdout``/``sys.stderr``; skipped under pytest unless ``force``."""
    if not force and running_under_pytest():
        return False
    try:
        for name, tag in (("stdout", "out"), ("stderr", "err")):
            stream = getattr(sys, name)
            if stream is None or isinstance(stream, TeeStream):
                continue
            setattr(sys, name, TeeStream(stream, run_log, tag))
        return True
    except Exception:  # noqa: BLE001 - fall back to reporter-only logging
        return False


def tee_active() -> bool:
    return isinstance(sys.stdout, TeeStream) or isinstance(sys.stderr, TeeStream)


def drain_tees() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, TeeStream):
            try:
                stream.drain()
            except Exception:  # noqa: BLE001
                pass


def uninstall_tee() -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if isinstance(stream, TeeStream):
            stream.drain()
            setattr(sys, name, stream._original)


__all__ = [
    "RunLog",
    "TeeStream",
    "drain_tees",
    "install_tee",
    "open_run_log",
    "run_log_path",
    "running_under_pytest",
    "tee_active",
    "uninstall_tee",
]
