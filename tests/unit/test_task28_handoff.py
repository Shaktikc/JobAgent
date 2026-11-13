"""The final handoff uses the live run's reporter even with a raw callback."""

import asyncio
from types import SimpleNamespace

from src.configuration import SessionSettings, Settings
from src.nodes.cleanup import cleanup
from src.state import Task4Outcome
from src.tools import browser
from src.tools.linkedin_status_overlay import _UPDATE_STATUS_JS, StatusReporter


async def test_cleanup_passes_the_registered_reporter(monkeypatch):
    reporter = StatusReporter()
    seen = []

    async def release(run_id, task4, progress):
        seen.append(progress)
        return "human"

    monkeypatch.setattr(browser, "get_reporter", lambda _: reporter)
    monkeypatch.setattr(browser, "release_run", release)
    await cleanup({"browser_run_id": "task28"})
    assert seen == [reporter]


async def test_release_handoff_reaches_panel_and_cli(tmp_path):
    observed, emitted, bypassed = [], [], []
    ready = asyncio.Event()

    class Page:
        async def evaluate(self, js, *args):
            if js == _UPDATE_STATUS_JS:
                observed.append(args)
                ready.set()

    page = Page()
    reporter = StatusReporter(emit=emitted.append, page=page)
    run_id = "task28-handoff"
    browser._ACTIVE_RUNS[run_id] = browser._Run(
        session=SimpleNamespace(is_cdp_connected=True), page=page, reporter=reporter,
    )
    settings = Settings(data_dir=tmp_path, session=SessionSettings(
        keep_open_timeout_seconds=0, keep_open_poll_seconds=0.01,
    ))
    task = asyncio.create_task(browser.release_run(
        run_id, Task4Outcome(reached_terminal_step=True), settings, bypassed.append,
    ))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert observed[-1] == (
            "waiting", "Waiting for you - review and submit the application in the page.",
        )
        assert emitted[-1] == observed[-1][1]
        assert not bypassed
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        browser.forget_run(run_id)
        await reporter.clear()
