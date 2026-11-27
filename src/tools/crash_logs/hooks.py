"""Install the global crash hooks and the run log (Task 33).

Installed only from the CLI entry point (never on import). Each hook writes a
bundle and then calls the previous hook, so the terminal traceback and exit code
are unchanged.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

from src.tools.crash_logs.config import load_crash_config
from src.tools.crash_logs.log_tee import install_tee, open_run_log, uninstall_tee
from src.tools.crash_logs.recorder import record_crash
from src.tools.crash_logs.runtime import RunContext, reset_run_context, run_context

_PREVIOUS: dict[str, object] = {}


def is_windows_pipe_noise(exc: BaseException | None) -> bool:
    """The known-harmless Windows shutdown artifact filtered in ``src.main``."""
    return (
        sys.platform == "win32"
        and isinstance(exc, ValueError)
        and "I/O operation on closed pipe" in str(exc)
    )


def _excepthook(exc_type, exc, tb) -> None:
    if exc is not None and not issubclass(exc_type, SystemExit):
        interrupted = issubclass(exc_type, KeyboardInterrupt)
        record_crash(
            "interrupted" if interrupted else "uncaught_exception",
            exc=exc,
            exit_code=130 if interrupted else 1,
        )
    previous = _PREVIOUS.get("excepthook") or sys.__excepthook__
    previous(exc_type, exc, tb)


def _thread_hook(args) -> None:
    if args.exc_type is not None and not issubclass(args.exc_type, SystemExit):
        record_crash(
            "thread_exception",
            exc=args.exc_value,
            extra={"thread": getattr(args.thread, "name", "") if args.thread else ""},
        )
    previous = _PREVIOUS.get("threading") or threading.__excepthook__
    previous(args)


def _unraisable_hook(unraisable) -> None:
    exc = getattr(unraisable, "exc_value", None)
    if not is_windows_pipe_noise(exc):
        record_crash(
            "unraisable_exception",
            exc=exc,
            message=str(getattr(unraisable, "err_msg", "") or ""),
            extra={"object": repr(getattr(unraisable, "object", None))[:1000]},
        )
    previous = _PREVIOUS.get("unraisable") or sys.__unraisablehook__
    previous(unraisable)


def install_asyncio_handler(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Record loop errors ("Task exception was never retrieved"…), then delegate."""
    try:
        loop = loop or asyncio.get_running_loop()
    except RuntimeError:
        return
    previous = loop.get_exception_handler()
    if getattr(previous, "_autojob_crash_handler", False):
        return

    def handler(the_loop, context: dict) -> None:
        exc = context.get("exception")
        if isinstance(exc, BaseException) and not isinstance(exc, asyncio.CancelledError):
            extra = {key: repr(value)[:1000] for key, value in context.items()
                     if key not in {"exception", "message"}}
            record_crash("asyncio_exception", exc=exc,
                         message=str(context.get("message") or ""), extra=extra)
        if previous is not None:
            previous(the_loop, context)
        else:
            the_loop.default_exception_handler(context)

    handler._autojob_crash_handler = True  # type: ignore[attr-defined]
    loop.set_exception_handler(handler)


def install_crash_logging(
    argv: list[str] | None = None,
    *,
    data_dir: Path | None = None,
    tee: bool | None = None,
) -> RunContext:
    """Idempotently set up the run context, run log, and global hooks. Never raises."""
    context = run_context()
    if context.installed:
        return context
    try:
        config = load_crash_config(data_dir)
        context = reset_run_context(argv=list(argv if argv is not None else sys.argv))
        context.config = config
        if not config.enabled:
            context.installed = True
            return context
        context.run_log = open_run_log(config, context.started_at, context.pid)
        if tee is not False and config.run_log:
            install_tee(context.run_log, force=bool(tee))
        _PREVIOUS["excepthook"] = sys.excepthook
        _PREVIOUS["threading"] = threading.excepthook
        _PREVIOUS["unraisable"] = sys.unraisablehook
        sys.excepthook = _excepthook
        threading.excepthook = _thread_hook
        sys.unraisablehook = _unraisable_hook
        context.installed = True
    except Exception as exc:  # noqa: BLE001 - the app must still run
        print(f"crash log   : crash logging unavailable ({exc})", file=sys.stderr)
    return context


def uninstall_crash_logging() -> None:
    """Restore hooks/streams (tests and embedded use)."""
    if sys.excepthook is _excepthook:
        sys.excepthook = _PREVIOUS.get("excepthook") or sys.__excepthook__
    if threading.excepthook is _thread_hook:
        threading.excepthook = _PREVIOUS.get("threading") or threading.__excepthook__
    if sys.unraisablehook is _unraisable_hook:
        sys.unraisablehook = _PREVIOUS.get("unraisable") or sys.__unraisablehook__
    uninstall_tee()
    context = run_context()
    if context.run_log is not None:
        context.run_log.close()
    _PREVIOUS.clear()
    reset_run_context()


__all__ = [
    "install_asyncio_handler",
    "install_crash_logging",
    "is_windows_pipe_noise",
    "uninstall_crash_logging",
]
