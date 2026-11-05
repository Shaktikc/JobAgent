"""Create dedicated browser sessions and manage their Chromium profile."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
from pathlib import Path

from src.configuration import Settings

_INSTALL_HINT = (
    "browser-use is not installed. Enable the optional extra:\n"
    "  uv sync --extra browser\n"
    "  uvx playwright install chromium"
)


def _require_browser_use():
    """Import browser-use on demand, with an actionable error if missing."""
    try:
        from browser_use import Browser
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(_INSTALL_HINT) from exc
    return Browser


# Chromium single-instance files left in the user-data-dir. While a browser owns
# the profile it holds a lock; a crashed/interrupted run can leave the lock files
# behind without a process.
_PROFILE_LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile")


def _profile_is_locked(profile_dir: Path) -> bool:
    """True when the profile looks owned by a browser (or a crashed one).

    A lock file alone does not prove the browser is gone: on Windows a *live*
    Chromium holds ``lockfile`` for as long as it runs. Callers that need to act
    on the lock must therefore also check :func:`_profile_browser_pids`.
    """
    return any((profile_dir / name).exists() for name in _PROFILE_LOCK_FILES)


def _clear_profile_locks(profile_dir: Path) -> None:
    """Remove Chromium's single-instance files so a fresh launch can take over."""
    for name in _PROFILE_LOCK_FILES:
        with contextlib.suppress(OSError):
            path = profile_dir / name
            if path.is_symlink() or path.exists():
                path.unlink()


def _profile_browser_pids(profile_dir: Path) -> list[int]:
    """Best-effort PIDs of chrome/chromium processes using this exact profile."""
    target = str(profile_dir)
    if sys.platform == "win32":
        script = (
            "$ErrorActionPreference='SilentlyContinue';"
            "Get-CimInstance Win32_Process -Filter "
            "\"Name='chrome.exe' OR Name='chromium.exe' OR Name='headless_shell.exe'\" | "
            "Where-Object { $_.CommandLine -like ('*' + $env:AUTOJOB_PROFILE + '*') } | "
            "ForEach-Object { $_.ProcessId }"
        )
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
        env = {**os.environ, "AUTOJOB_PROFILE": target}
    else:
        cmd = ["pgrep", "-f", target]
        env = None
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=20, env=env, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(line) for line in result.stdout.splitlines() if line.strip().isdigit()]


def terminate_profile_browsers(profile_dir: Path) -> int:
    """Kill every browser still holding ``profile_dir``; return how many.

    This is the **explicit** escape hatch (the ``--clean-profile`` command and
    :func:`clean_profile`). It is intentionally aggressive: it force-closes any
    browser whose command line references this dedicated profile, including a
    live one. Automatic recovery must **not** call it — force-killing a browser
    that another run is driving makes that run's CDP WebSocket drop and every
    reconnect fail (``ConnectionRefusedError``). Only processes whose command
    line references this dedicated profile are touched, so a normal Chrome is
    never affected.
    """
    pids = _profile_browser_pids(profile_dir)
    for pid in pids:
        if sys.platform == "win32":
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
        else:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)
    return len(pids)


def clean_profile(settings: Settings) -> int:
    """Close every browser using the profile and clear its lock files.

    Explicit and destructive: used by ``autojob --clean-profile`` when the user
    wants to force-recover a profile, even if a browser is still driving it.
    """
    settings.profile_dir.mkdir(parents=True, exist_ok=True)
    killed = terminate_profile_browsers(settings.profile_dir)
    _clear_profile_locks(settings.profile_dir)
    return killed


def build_browser(settings: Settings):
    """Build a Chromium session that persists logins in ``data/profile``.

    A profile lock left by a **crashed** run is recovered by clearing the stale
    lock files. A lock held by a **live** browser is never force-killed: doing so
    was the cause of a second run tearing down the first run's CDP WebSocket
    (``CDP WebSocket message handler exited`` followed by reconnection attempts
    that fail with ``ConnectionRefusedError`` / ``WinError 1225``). Instead the
    launch stops with an actionable error so the caller can finish or close the
    other run (or the user can run ``autojob --clean-profile`` deliberately).
    """
    Browser = _require_browser_use()
    settings.profile_dir.mkdir(parents=True, exist_ok=True)
    if settings.session.clean_stale_profile and _profile_is_locked(settings.profile_dir):
        live = _profile_browser_pids(settings.profile_dir)
        if live:
            pids = ", ".join(str(pid) for pid in live)
            raise RuntimeError(
                "another browser is already using the JobAgent profile "
                f"{settings.profile_dir} (process id(s): {pids}). Close that "
                "window (or wait for the other run to finish), then retry; to "
                "force-close it run `autojob --clean-profile`."
            )
        # The lock has no live owner: a crashed/interrupted run left it behind.
        # Clearing it lets this launch open its own CDP port instead of handing
        # off to a browser that no longer exists.
        _clear_profile_locks(settings.profile_dir)
    return Browser(
        headless=settings.session.headless,
        user_data_dir=str(settings.profile_dir),
        viewport=settings.session.viewport,
        user_agent=settings.session.user_agent,
        # The agent never closes the browser (see ``close_run``): keep the Chromium
        # process alive when our CDP handle is released, so a failure or a finished
        # run can still be inspected and driven by the human. Only the explicit
        # ``autojob --clean-profile`` force-closes a browser.
        keep_alive=True,
    )
