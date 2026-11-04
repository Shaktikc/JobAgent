"""Live run registry, final human review, and browser detachment."""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass

from src.configuration import Settings, load_settings
from src.state import Task4Outcome
from src.tools.linkedin_status_overlay import emit_step, release_interaction_lock


@dataclass
class _Run:
    """A live browser session kept open across graph nodes."""

    session: object
    page: object
    # Task 9: the status reporter bound to this run's page (CLI + on-page panel).
    reporter: object = None


# run_id -> live session, so Tasks 2-4 can share one browser window without
# putting the (un-serializable) session object into the graph state.
_ACTIVE_RUNS: dict[str, _Run] = {}


def get_run(run_id: str | None) -> _Run | None:
    """Return the registered live session for ``run_id``, if any."""
    return _ACTIVE_RUNS.get(run_id) if run_id else None


def get_reporter(run_id: str | None):
    """Task 9: the run's status reporter, or ``None`` when the run is gone."""
    run = get_run(run_id)
    return getattr(run, "reporter", None) if run is not None else None


async def _detach_session(session) -> None:
    """Release our handle on a browser session **without closing the window**.

    ``browser-use``'s ``stop()`` tears down our CDP link and event bus while the
    ``keep_alive`` profile keeps the session from resetting. Its
    ``LocalBrowserWatchdog`` would still force-kill the Chromium subprocess, so we
    first clear the watchdog's process handle — with nothing to terminate, the
    window stays open. ``kill()`` is deliberately never called; only the explicit
    ``autojob --clean-profile`` force-closes a browser. A session without
    ``stop()`` (e.g. a test fake) is simply left untouched.
    """
    watchdog = getattr(session, "_local_browser_watchdog", None)
    if watchdog is not None:
        with contextlib.suppress(Exception):
            watchdog._subprocess = None  # type: ignore[attr-defined]
            watchdog._owns_browser_resources = False  # type: ignore[attr-defined]
    stop = getattr(session, "stop", None)
    if stop is None:
        return
    with contextlib.suppress(Exception):
        await stop()


async def close_run(run_id: str | None) -> None:
    """Release the run registered under ``run_id`` without closing the browser.

    Idempotent. The agent **never** closes the browser: this only forgets the run
    and detaches our CDP handle, so the Chromium window stays open (see
    :func:`_detach_session`).
    """
    if not run_id:
        return
    run = _ACTIVE_RUNS.pop(run_id, None)
    if run is None:
        return
    # Task 9: remove the on-page status panel before the CDP handle is detached,
    # so no stale status is left behind (best-effort; never fails the release).
    reporter = getattr(run, "reporter", None)
    if reporter is not None:
        with contextlib.suppress(Exception):
            await reporter.clear()
    # Runs without a reporter still own a renderer input lock. Unlock before
    # detaching, while CDP is available, so the open window remains usable.
    await release_interaction_lock(run.page)
    await _detach_session(run.session)


def forget_run(run_id: str | None) -> None:
    """Forget a run whose browser is already gone (no kill attempt).

    Used when a live CDP connection drops (the human closed the window): there is
    nothing to kill, so the run is simply removed from the registry.
    """
    if run_id:
        _ACTIVE_RUNS.pop(run_id, None)


def run_is_connected(run_id: str | None) -> bool:
    """True while the run's browser still has a live CDP connection.

    A missing run is treated as not connected; a session that does not expose
    ``is_cdp_connected`` is treated as still alive, so the caller never closes a
    window it cannot confirm is gone.
    """
    run = get_run(run_id)
    if run is None:
        return False
    return bool(getattr(run.session, "is_cdp_connected", True))


async def wait_for_human_close(
    run_id: str | None,
    settings: Settings | None = None,
    progress=None,
) -> bool:
    """Leave the run's browser open and wait for the human to close it.

    Used when Task 4 stops at the terminal step (only **Submit application**
    remains): the window stays open so the human can review and submit the
    application manually, then closes it. Returns ``True`` once the browser is
    gone (closed by the human), or ``False`` when the wait times out — the run
    stops waiting but the browser is **left open** for the human (the agent never
    closes it). ``AUTOJOB_SESSION_KEEP_OPEN_TIMEOUT_SECONDS`` of ``0`` waits
    indefinitely.
    """
    settings = settings or load_settings()
    notify = progress or (lambda _message: None)
    run = get_run(run_id)
    if run is None:
        return True

    # Automation has finished on this path; no later step will reclaim the page.
    # Release the watcher before announcing the handoff, including on cancellation.
    release_input = getattr(run.reporter, "release_input", None)
    if callable(release_input):
        await release_input()
    await release_interaction_lock(run.page)
    timeout = settings.session.keep_open_timeout_seconds
    poll = settings.session.keep_open_poll_seconds
    notify(
        "Task 4: reached the last step; leaving the browser open. Review and "
        "submit the application yourself, then close the browser window to "
        "finish the run."
    )
    emit_step(progress, "Waiting for you - review and submit the application in the page.")
    deadline = None if timeout <= 0 else time.monotonic() + timeout
    while True:
        if not run_is_connected(run_id):
            forget_run(run_id)
            return True
        if deadline is not None and time.monotonic() >= deadline:
            notify("Task 4: browser still open after the wait; leaving it open.")
            await close_run(run_id)
            return False
        await asyncio.sleep(poll)


async def release_run(
    run_id: str | None,
    task4: Task4Outcome | None = None,
    settings: Settings | None = None,
    progress=None,
) -> str:
    """Release the run's browser, respecting the human's final Submit step.

    When Task 4 stopped at the terminal step (only **Submit application** remains)
    the window is left open and this waits for the human to close it (see
    :func:`wait_for_human_close`). On every other path the run is released but the
    browser is **left open** — the agent never closes it. Returns ``"human"``
    (closed by the human), ``"timeout"`` (the wait ended; left open), or
    ``"closed"`` (the run was released; the window is left open).
    """
    if task4 is not None and task4.awaiting_human_submit:
        return "human" if await wait_for_human_close(run_id, settings, progress) else "timeout"
    await close_run(run_id)
    return "closed"
