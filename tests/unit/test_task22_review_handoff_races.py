"""Cancellation and deferred installation must never strand renderer input."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.configuration import SessionSettings, Settings
from src.tools import browser as browser_tools
from src.tools import linkedin_apply_loop as apply_loop
from src.tools import linkedin_status_overlay as status


class _Input:
    def __init__(self):
        self.ignored = False
        self.pause_unlock = False
        self.unlock_started = asyncio.Event()
        self.allow_unlock = asyncio.Event()

    async def setIgnoreInputEvents(self, params, session_id=None):
        if not params["ignore"] and self.pause_unlock:
            self.unlock_started.set()
            await self.allow_unlock.wait()
        self.ignored = params["ignore"]


class _Page:
    session_id = "review-race-session"

    def __init__(self):
        self.input = _Input()
        self._client = SimpleNamespace(send=SimpleNamespace(Input=self.input))

    async def get_url(self):
        return "https://www.linkedin.com/jobs/view/123/"

    async def evaluate(self, *_):
        return False


def _register(page, reporter=None):
    run_id = "task22-review-race"
    session = SimpleNamespace(is_cdp_connected=True)
    browser_tools._ACTIVE_RUNS[run_id] = browser_tools._Run(
        page=page, session=session, reporter=reporter,
    )
    return run_id, session


def _settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", session=SessionSettings(
        keep_open_timeout_seconds=0, keep_open_poll_seconds=0.01,
    ))


@pytest.mark.parametrize("waiter", ["final_review", "manual_submit"])
async def test_cancellation_while_initial_unlock_is_pending_finishes_the_unlock(
    tmp_path, waiter,
):
    page = _Page()
    run_id, _ = _register(page)
    lock = await status.ensure_interaction_lock(page)
    assert lock is not None
    assert page.input.ignored
    page.input.pause_unlock = True
    wait = (browser_tools.wait_for_human_close if waiter == "final_review"
            else apply_loop.await_human_submit)
    task = asyncio.create_task(wait(run_id, _settings(tmp_path)))
    try:
        await asyncio.wait_for(page.input.unlock_started.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        page.input.allow_unlock.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        await lock._refresh()
        assert not page.input.ignored, "cancelling the pending CDP write stranded input"
    finally:
        page.input.allow_unlock.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        browser_tools.forget_run(run_id)
        await status.release_interaction_lock(page)


async def test_pending_reporter_install_cannot_relock_a_direct_final_review_wait(tmp_path):
    page = _Page()
    reporter = status.StatusReporter()
    reporter.bind_page(page)
    run_id, session = _register(page, reporter)
    announced = asyncio.Event()
    observed = []

    async def inspect_handoff():
        await announced.wait()
        await asyncio.sleep(0)
        observed.append(page.input.ignored)
        session.is_cdp_connected = False

    observer = asyncio.create_task(inspect_handoff())
    try:
        # Deliberately await directly: wrapping the waiter in create_task lets
        # the queued installer run first and hides the late-installation race.
        async with asyncio.timeout(1):
            result = await browser_tools.wait_for_human_close(
                run_id, _settings(tmp_path), progress=lambda _: announced.set(),
            )
        await asyncio.wait_for(observer, 1)
        assert result is True
        assert observed == [False], "deferred reporter installation re-locked human review"
        assert not page.input.ignored
    finally:
        observer.cancel()
        await asyncio.gather(observer, return_exceptions=True)
        browser_tools.forget_run(run_id)
        await reporter.clear()
        await status.release_interaction_lock(page)


async def test_reporter_clear_waits_for_its_pending_interaction_lock_installation():
    page = _Page()
    reporter = status.StatusReporter()
    reporter.bind_page(page)
    try:
        await reporter.clear()
        await asyncio.sleep(0)
        assert not page.input.ignored, "cleared reporter installed a new input lock afterward"
    finally:
        await status.release_interaction_lock(page)
