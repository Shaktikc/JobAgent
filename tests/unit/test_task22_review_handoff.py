"""Human review must remain interactive after automation gives up ownership."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task4Outcome
from src.tools import browser as browser_tools
from src.tools import linkedin_apply_loop as apply_loop
from src.tools import linkedin_status_overlay as status


class _Input:
    def __init__(self):
        self.ignored = False
        self.clicks = 0

    async def setIgnoreInputEvents(self, params, session_id=None):
        self.ignored = params["ignore"]

    async def dispatchMouseEvent(self, params, session_id=None):
        if not self.ignored:
            self.clicks += 1


class _Page:
    session_id = "review-session"

    def __init__(self):
        self.input = _Input()
        self._client = SimpleNamespace(send=SimpleNamespace(Input=self.input))

    async def get_url(self):
        return "https://www.linkedin.com/jobs/view/123/"

    async def evaluate(self, *_):
        return False


def _settings(tmp_path, timeout=0.05):
    return Settings(data_dir=tmp_path / "data", session=SessionSettings(
        keep_open_timeout_seconds=timeout, keep_open_poll_seconds=0.01,
    ))


def _register(page):
    async def stop():
        pass

    run_id = "task22-review-handoff"
    browser_tools._ACTIVE_RUNS[run_id] = browser_tools._Run(
        session=SimpleNamespace(is_cdp_connected=True, stop=stop), page=page,
    )
    return run_id


async def _wait(entrypoint, run_id, settings, notify):
    if entrypoint == "release_run":
        return await browser_tools.release_run(
            run_id, Task4Outcome(reached_terminal_step=True), settings, notify,
        )
    return await browser_tools.wait_for_human_close(run_id, settings, notify)


@pytest.mark.parametrize("entrypoint", ["wait_for_human_close", "release_run"])
async def test_final_review_unlocks_before_asking_and_stays_interactive_on_timeout(
    tmp_path, entrypoint,
):
    page = _Page()
    raw_click = page.input.dispatchMouseEvent
    run_id = _register(page)
    lock = await status.ensure_interaction_lock(page)
    assert lock is not None
    observed = []

    def notify(_message):
        observed.append(page.input.ignored)

    try:
        await raw_click({})
        assert page.input.clicks == 0, "automation must ignore unwrapped input"
        result = await _wait(entrypoint, run_id, _settings(tmp_path), notify)
        assert observed and observed[0] is False, "unlock before asking the human to review"
        assert result == ("timeout" if entrypoint == "release_run" else False)
        await lock._refresh()
        await raw_click({})
        assert page.input.clicks == 1, "the open page must stay interactive after timeout"
    finally:
        browser_tools.forget_run(run_id)
        await status.release_interaction_lock(page)


@pytest.mark.parametrize("entrypoint", ["wait_for_human_close", "release_run"])
async def test_cancelled_final_review_leaves_the_open_page_interactive(tmp_path, entrypoint):
    page = _Page()
    raw_click = page.input.dispatchMouseEvent
    run_id = _register(page)
    lock = await status.ensure_interaction_lock(page)
    assert lock is not None
    ready = asyncio.Event()
    task = asyncio.create_task(_wait(
        entrypoint, run_id, _settings(tmp_path, timeout=0), lambda _: ready.set(),
    ))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await lock._refresh()
        await raw_click({})
        assert page.input.clicks == 1, "cancellation must not strand the browser input lock"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        browser_tools.forget_run(run_id)
        await status.release_interaction_lock(page)


@pytest.mark.parametrize("result", ["submitted", "timeout", "closed"])
async def test_manual_submit_wait_restores_automation_only_after_confirmation(
    tmp_path, monkeypatch, result,
):
    page = _Page()
    raw_click = page.input.dispatchMouseEvent
    run_id = _register(page)
    lock = await status.ensure_interaction_lock(page)
    assert lock is not None

    async def observe(*_, **__):
        await raw_click({})
        assert page.input.clicks == 1, "the human's submit turn must be interactive"
        return result

    monkeypatch.setattr(apply_loop, "_await_human_submit", observe)
    try:
        assert await apply_loop.await_human_submit(run_id, _settings(tmp_path)) == result
        await lock._refresh()
        await raw_click({})
        assert page.input.clicks == (1 if result == "submitted" else 2), (
            "only a confirmed submission hands input ownership back to automation"
        )
    finally:
        browser_tools.forget_run(run_id)
        await status.release_interaction_lock(page)
