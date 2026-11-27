"""Exception, environment, settings, state, and job snapshots (Task 33)."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
import threading
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.tools.crash_logs.config import PROJECT_ROOT
from src.tools.crash_logs.redact import REDACTED, Clipper, is_sensitive_key

MAX_LOCAL_CHARS = 1_000
_GIT_CACHE: dict[str, Any] = {}
_JOB_ID = re.compile(r"/jobs/view/(\d+)|currentJobId=(\d+)")


def _chain(exc: BaseException) -> list[BaseException]:
    """``exc`` then its causes/contexts, oldest last, without cycles."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(chain) < 20:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return chain


def _in_project(filename: str) -> bool:
    try:
        path = Path(filename).resolve()
    except (OSError, ValueError):
        return False
    return path.is_relative_to(PROJECT_ROOT) and ".venv" not in path.parts


def _frames(exc: BaseException, include_locals: bool, clipper: Clipper) -> list[dict]:
    frames: list[dict] = []
    tb = exc.__traceback__
    while tb is not None and len(frames) < 200:
        frame = tb.tb_frame
        summary = traceback.FrameSummary(
            frame.f_code.co_filename, tb.tb_lineno, frame.f_code.co_name
        )
        item = {
            "file": summary.filename,
            "line": summary.lineno,
            "function": summary.name,
            "source": (summary.line or "").strip(),
        }
        if include_locals and _in_project(summary.filename):
            local_vars = {}
            for name, value in list(frame.f_locals.items())[:60]:
                try:
                    text = repr(value)
                except Exception as error:  # noqa: BLE001
                    text = f"<repr failed: {error}>"
                local_vars[name] = text
            item["locals"] = {
                key: REDACTED if is_sensitive_key(key)
                else clipper.text(text, f"locals.{key}", MAX_LOCAL_CHARS)
                for key, text in local_vars.items()
            }
        frames.append(item)
        tb = tb.tb_next
    return frames


def exception_info(
    exc: BaseException | None, *, include_locals: bool, clipper: Clipper
) -> dict:
    """Type, message, full traceback, the cause chain, and every frame."""
    if exc is None:
        return {"type": "", "message": "", "traceback": "(none)", "chain": [], "frames": []}
    try:
        full = "".join(traceback.format_exception(exc))
    except Exception as error:  # noqa: BLE001
        full = f"(traceback unavailable: {error})"
    chain = []
    for item in _chain(exc)[1:]:
        chain.append(
            {
                "type": type(item).__name__,
                "message": clipper.text(str(item), "exception.chain.message"),
                "traceback": clipper.text(
                    "".join(traceback.format_exception(item, chain=False)),
                    "exception.chain.traceback",
                    20_000,
                ),
            }
        )
    return {
        "type": type(exc).__name__,
        "module": type(exc).__module__,
        "message": clipper.text(str(exc), "exception.message"),
        "traceback": clipper.text(full, "exception.traceback", 200_000),
        "chain": chain,
        "frames": _frames(exc, include_locals, clipper),
    }


def git_info() -> dict:
    if _GIT_CACHE:
        return dict(_GIT_CACHE)
    info = {"git_commit": "", "git_dirty": None}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=3, check=False,
        )
        info["git_commit"] = commit.stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=3, check=False,
        )
        info["git_dirty"] = bool(status.stdout.strip()) if status.returncode == 0 else None
    except Exception:  # noqa: BLE001 - git is optional evidence
        pass
    _GIT_CACHE.update(info)
    return info


def run_info(context, run_id: str, captured_at: datetime) -> dict:
    started = context.started_at
    return {
        "run_id": run_id,
        "pid": context.pid,
        "argv": list(context.argv),
        "cwd": os.getcwd(),
        "python": platform.python_version(),
        "executable": sys.executable,
        "platform": platform.platform(),
        **git_info(),
        "started_at": started.isoformat(),
        "duration_seconds": round((captured_at - started).total_seconds(), 3),
        "thread": threading.current_thread().name,
    }


def settings_snapshot(clipper: Clipper) -> dict:
    """The redacted app settings, or why they could not be read."""
    try:
        from src.configuration import load_settings

        settings = load_settings()
        return clipper.clean(settings.model_dump(mode="json"), "settings")
    except Exception as exc:  # noqa: BLE001 - settings may be the crash
        return {"error": clipper.text(f"settings unavailable: {exc}", "settings")}


def _attr(obj: Any, name: str) -> str:
    if obj is None:
        return ""
    value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, "")
    return str(value or "")


def job_info(state: dict | None) -> dict:
    """Job id/URL/title/company from whatever the state knows."""
    state = state or {}
    description = state.get("job_description")
    task2 = state.get("task2")
    task4 = state.get("task4")
    url = _attr(description, "page_url") or _attr(task2, "job_url") or _attr(task2, "page_url")
    url = url or _attr(task4, "job_url")
    match = _JOB_ID.search(url or "")
    return {
        "id": (match.group(1) or match.group(2)) if match else "",
        "url": url,
        "title": _attr(description, "title") or _attr(task2, "job_title"),
        "company": _attr(description, "company") or _attr(task2, "company"),
    }


def self_healing_link(state: dict | None) -> dict:
    """Reference the self-healing bundle/bug instead of copying its evidence."""
    outcome = (state or {}).get("self_healing")
    if outcome is None:
        return {}
    bug_ids = list(getattr(outcome, "bug_ids", None) or [])
    return {
        "bug_id": bug_ids[-1] if bug_ids else "",
        "bug_ids": bug_ids,
        "bundle": str(getattr(outcome, "last_bundle", "") or ""),
        "attempts": int(getattr(outcome, "attempts", 0) or 0),
        "recovered": bool(getattr(outcome, "recovered", False)),
        "exhausted": bool(getattr(outcome, "exhausted", False)),
        "stop_reason": str(getattr(outcome, "stop_reason", "") or ""),
    }


def now_utc() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "exception_info",
    "git_info",
    "job_info",
    "now_utc",
    "run_info",
    "self_healing_link",
    "settings_snapshot",
]
