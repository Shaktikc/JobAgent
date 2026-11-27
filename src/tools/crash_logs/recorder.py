"""Build and write one crash bundle per crash (Task 33).

Everything here is best-effort: the public functions never raise, never change
the caller's control flow, and report a write failure as one concise line.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from src.tools.crash_logs import browser as browser_capture
from src.tools.crash_logs.config import CrashLogConfig, load_crash_config
from src.tools.crash_logs.context import (
    exception_info,
    job_info,
    now_utc,
    run_info,
    self_healing_link,
    settings_snapshot,
)
from src.tools.crash_logs.models import SCHEMA_VERSION, CrashRecord, index_row
from src.tools.crash_logs.redact import Clipper, is_sensitive_key, scrub_text
from src.tools.crash_logs.report import render_report
from src.tools.crash_logs.runtime import run_context
from src.tools.crash_logs.store import (
    append_index,
    clip_state_json,
    dumps,
    new_crash_id,
    prune,
    reserve_bundle,
    write_files,
)

_MARKER = "__autojob_crash_bundle__"


def _config() -> CrashLogConfig:
    context = run_context()
    if context.config is None:
        context.config = load_crash_config()
    return context.config


def already_recorded(exc: BaseException | None) -> bool:
    if exc is None:
        return False
    return bool(getattr(exc, _MARKER, "")) or id(exc) in run_context().recorded_exc_ids


def _mark(exc: BaseException | None, bundle: str) -> None:
    if exc is None:
        return
    run_context().recorded_exc_ids.add(id(exc))
    try:
        setattr(exc, _MARKER, bundle or "pending")
    except Exception:  # noqa: BLE001 - some exceptions forbid attributes
        pass


def _dedupe_key(kind: str, exc: BaseException | None, stage: str, message: str) -> str:
    if kind == "interrupted":
        return "interrupted"
    if exc is None:
        return f"{kind}|{stage}|{message}"
    tb = exc.__traceback__
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    top = f"{tb.tb_frame.f_code.co_filename}:{tb.tb_lineno}" if tb is not None else ""
    return f"exc|{type(exc).__name__}|{exc}|{top}"


def _notify(message: str) -> None:
    """One concise stderr line (paths only; never bundle contents)."""
    try:
        print(message, file=sys.stderr or sys.__stderr__, flush=True)
    except Exception:  # noqa: BLE001
        pass


def _begin(kind, exc, stage, state, message) -> dict | None:
    config = _config()
    if not config.enabled:
        return None
    context = run_context()
    stage = stage if stage is not None else context.stage
    if state is None:
        state = context.state
    with context.lock:
        if already_recorded(exc):
            return None
        key = _dedupe_key(kind, exc, stage or "", message or "")
        if key in context.recorded_keys:
            return None
        context.recorded_keys.add(key)
        _mark(exc, "")
    captured = now_utc()
    crash_id, bundle = reserve_bundle(config.crash_dir, new_crash_id(captured))
    return {
        "config": config,
        "kind": kind,
        "exc": exc,
        "stage": stage or "",
        "state": state if isinstance(state, dict) else {},
        "message": message or "",
        "captured": captured,
        "crash_id": crash_id,
        "bundle": bundle,
        "clipper": Clipper(),
    }


def _env_vars(clipper: Clipper) -> dict:
    result = {}
    for name in sorted(os.environ):
        if name.startswith(("AUTOJOB_", "OPENROUTER_", "OPENAI_")):
            value = os.environ[name]
            result[name] = "[redacted]" if is_sensitive_key(name) else clipper.text(value, name)
    return result


def _finish(plan: dict, *, exit_code, extra, browser: dict, healing: dict | None) -> str:
    config: CrashLogConfig = plan["config"]
    clipper: Clipper = plan["clipper"]
    context = run_context()
    state = plan["state"]
    bundle: Path = plan["bundle"]
    exc = plan["exc"]
    run_id = str(state.get("browser_run_id") or browser.get("run_id") or "")
    run = run_info(context, run_id, plan["captured"])
    exception = exception_info(exc, include_locals=config.include_locals, clipper=clipper)
    if exc is None and plan.get("traceback_text"):
        exception["message"] = clipper.text(plan["message"], "exception.message")
        exception["traceback"] = clipper.text(plan["traceback_text"], "traceback", 200_000)
    safe_state = clipper.clean(state, "state")
    settings = settings_snapshot(clipper)
    run_log = context.run_log
    tail = [scrub_text(line) for line in (run_log.tail_lines() if run_log else [])]
    log_info = {
        "path": str(getattr(run_log, "path", "") or ""),
        "tail_lines": len(tail),
        "total_lines": int(getattr(run_log, "total_lines", 0) or 0),
        "truncated": bool(getattr(run_log, "truncated", False)),
    }
    record: CrashRecord = {
        "schema_version": SCHEMA_VERSION,
        "crash_id": plan["crash_id"],
        "captured_at": plan["captured"].isoformat(),
        "kind": plan["kind"],
        "stage": plan["stage"],
        "exit_code": exit_code,
        "message": clipper.text(plan["message"], "message"),
        "run": run,
        "exception": exception,
        "job": job_info(state),
        "state": safe_state,
        "settings": settings,
        "run_log": {**log_info, "tail": tail[-50:]},
        "browser": browser,
        "self_healing": healing if healing is not None else self_healing_link(state),
        "context": clipper.clean(extra or {}, "context"),
        "errors": [clipper.text(str(e), "errors") for e in state.get("errors") or []],
        "log": [clipper.text(str(e), "log") for e in (state.get("log") or [])[-200:]],
    }
    notes = clipper.notes
    state_text = clip_state_json(safe_state, notes)
    record["truncation"] = list(notes)
    env = {**run, "settings": settings, "environment": _env_vars(clipper)}
    files: dict[str, str | bytes] = {
        "traceback.txt": (exception.get("traceback") or "(none)") + "\n",
        "state.json": state_text,
        "run.log": "\n".join(tail) + ("\n" if tail else "(run log empty or not installed)\n"),
        "env.json": dumps(env),
        "report.md": render_report(record),
        "crash.json": dumps(record),
    }
    write_files(bundle, files)
    relative = _display_path(bundle)
    quarantined = append_index(config.crash_dir, index_row(record, relative))
    if quarantined is not None:
        _notify(f"crash log   : unreadable index moved to {quarantined.name}")
    prune(config.crash_dir, max_bundles=config.max_bundles, max_days=config.max_days,
          keep=bundle.name)
    context.bundles.append(str(bundle))
    _mark(exc, str(bundle))
    _notify(f"crash log   : {relative}")
    return str(bundle)


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _no_page(plan: dict, reason: str) -> dict:
    return {"run_id": str(plan["state"].get("browser_run_id") or ""), "page_url": "",
            "page_title": "", "screenshot": "", "dom": "", "page_text": "", "console": "",
            "error": reason}


def record_crash(
    kind: str,
    *,
    exc: BaseException | None = None,
    stage: str | None = None,
    state: dict | None = None,
    exit_code: int | None = None,
    message: str = "",
    extra: dict | None = None,
    self_healing: dict | None = None,
    traceback_text: str = "",
) -> str | None:
    """Write a bundle synchronously (no page capture). Returns its path or ``None``."""
    try:
        plan = _begin(kind, exc, stage, state, message)
        if plan is None:
            return None
        plan["traceback_text"] = traceback_text
        live = browser_capture.page_available(str(plan["state"].get("browser_run_id") or ""))
        reason = "page capture needs the running event loop" if live else "no live browser page"
        return _finish(plan, exit_code=exit_code, extra=extra,
                       browser=_no_page(plan, reason), healing=self_healing)
    except Exception as error:  # noqa: BLE001 - never replace the original crash
        _notify(f"crash log   : could not write the crash bundle ({error})")
        return None


async def record_crash_async(
    kind: str,
    *,
    exc: BaseException | None = None,
    stage: str | None = None,
    state: dict | None = None,
    exit_code: int | None = None,
    message: str = "",
    extra: dict | None = None,
    self_healing: dict | None = None,
    capture_page: bool = True,
    traceback_text: str = "",
) -> str | None:
    """Write a bundle with best-effort live-page evidence. Never raises."""
    try:
        plan = _begin(kind, exc, stage, state, message)
        if plan is None:
            return None
        plan["traceback_text"] = traceback_text
        if capture_page:
            run_id = str(plan["state"].get("browser_run_id") or "")
            page = await browser_capture.capture_page(run_id, plan["bundle"], plan["clipper"])
        else:
            page = _no_page(plan, "page capture skipped")
        return _finish(plan, exit_code=exit_code, extra=extra, browser=page,
                       healing=self_healing)
    except BaseException as error:  # noqa: BLE001 - incl. cancellation mid-capture
        _notify(f"crash log   : could not write the crash bundle ({error!r})")
        if not isinstance(error, Exception):
            raise
        return None


def record_exception(exc: BaseException, kind: str = "uncaught_exception", **kwargs: Any):
    """Synchronous shortcut for an exception crash."""
    return record_crash(kind, exc=exc, **kwargs)


__all__ = ["already_recorded", "record_crash", "record_crash_async", "record_exception"]
