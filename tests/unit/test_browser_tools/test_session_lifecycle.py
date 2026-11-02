"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

import pytest

from src.state import DEFAULT_LOGIN_URL, Task4Outcome
from src.tools import browser as browser_tools
from src.tools.linkedin import build_jobs_search_url

from .fakes import FakeElement, FakePage, FakeSession
from .helpers import (
    _filter_element,
    _job_card,
    _settings,
)

SEARCH_URL = build_jobs_search_url("software engineer")


async def test_run_agent_registers_and_closes_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(
        results_count=25,
        details_apply_labels={0: "Easy Apply to Backend Engineer at Acme"},
    )
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [_filter_element(page)],
        "li.jobs-search-results__list-item": [_job_card(page, 0, "Backend Engineer")],
    }
    session = FakeSession(page)
    monkeypatch.setattr(browser_tools, "build_browser", lambda settings: session)

    result = await browser_tools.run_agent(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert result.task2.application_form_opened is True
    assert result.job_description.is_read is True
    # run_agent does not fill the form; the graph's fill node does.
    assert result.task4.form_open is False
    assert session.killed is False
    assert session.stopped is True
    assert browser_tools._ACTIVE_RUNS == {}


async def test_start_tasks_keeps_the_session_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(
        results_count=25,
        details_apply_labels={0: "Easy Apply to Backend Engineer at Acme"},
    )
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [_filter_element(page)],
        "li.jobs-search-results__list-item": [_job_card(page, 0, "Backend Engineer")],
    }
    session = FakeSession(page)
    monkeypatch.setattr(browser_tools, "build_browser", lambda settings: session)

    _outcome, run_id = await browser_tools.start_tasks(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert run_id is not None
    assert session.killed is False
    assert browser_tools.get_run(run_id) is not None

    await browser_tools.close_run(run_id)
    # Releasing the run must never close the browser.
    assert session.killed is False
    assert session.stopped is True
    assert browser_tools.get_run(run_id) is None


async def test_detach_session_never_kills_the_browser() -> None:
    """Releasing a session detaches our handle and disarms the kill watchdog."""

    class _Watchdog:
        _subprocess = object()
        _owns_browser_resources = True

    class _Session:
        def __init__(self) -> None:
            self._local_browser_watchdog = _Watchdog()
            self.stopped = False
            self.killed = False

        async def stop(self) -> None:
            self.stopped = True

        async def kill(self) -> None:
            self.killed = True

    session = _Session()
    await browser_tools._detach_session(session)

    assert session.stopped is True
    assert session.killed is False
    # With no subprocess handle the local-browser watchdog cannot force-kill it.
    assert session._local_browser_watchdog._subprocess is None
    assert session._local_browser_watchdog._owns_browser_resources is False


def test_run_is_connected_is_false_without_a_run() -> None:
    assert browser_tools.run_is_connected(None) is False
    assert browser_tools.run_is_connected("missing") is False


async def test_wait_for_human_close_returns_when_the_human_closes(tmp_path) -> None:
    page = FakePage()
    session = FakeSession(page)
    session.is_cdp_connected = False  # the human has closed the window
    run_id = "run-closed"
    browser_tools._ACTIVE_RUNS[run_id] = browser_tools._Run(session=session, page=page)

    try:
        closed = await browser_tools.wait_for_human_close(run_id, _settings(tmp_path))
    finally:
        browser_tools._ACTIVE_RUNS.pop(run_id, None)

    assert closed is True
    # The window is already gone; nothing to kill.
    assert session.killed is False
    assert browser_tools.get_run(run_id) is None


async def test_wait_for_human_close_times_out_and_leaves_open(tmp_path) -> None:
    page = FakePage()
    session = FakeSession(page)
    session.is_cdp_connected = True  # the window stays open
    run_id = "run-timeout"
    browser_tools._ACTIVE_RUNS[run_id] = browser_tools._Run(session=session, page=page)

    try:
        closed = await browser_tools.wait_for_human_close(
            run_id,
            _settings(tmp_path, keep_open_timeout_seconds=0.05, keep_open_poll_seconds=0.01),
        )
    finally:
        browser_tools._ACTIVE_RUNS.pop(run_id, None)

    assert closed is False
    assert session.killed is False
    assert session.stopped is True
    assert browser_tools.get_run(run_id) is None


async def test_release_run_waits_for_the_human_at_the_terminal_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    calls: dict = {}

    async def fake_wait(run_id, settings=None, progress=None):
        calls["waited"] = run_id
        return True

    async def fake_close(run_id):
        calls["closed"] = run_id

    monkeypatch.setattr(browser_tools, "wait_for_human_close", fake_wait)
    monkeypatch.setattr(browser_tools, "close_run", fake_close)

    released = await browser_tools.release_run(
        "run-1", Task4Outcome(reached_terminal_step=True), _settings(tmp_path)
    )

    assert released == "human"
    assert calls["waited"] == "run-1"
    assert "closed" not in calls


async def test_release_run_closes_when_not_at_the_terminal_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    calls: dict = {}

    async def fake_wait(run_id, settings=None, progress=None):
        calls["waited"] = run_id
        return True

    async def fake_close(run_id):
        calls["closed"] = run_id

    monkeypatch.setattr(browser_tools, "wait_for_human_close", fake_wait)
    monkeypatch.setattr(browser_tools, "close_run", fake_close)

    released = await browser_tools.release_run("run-1", Task4Outcome(), _settings(tmp_path))

    assert released == "closed"
    assert calls["closed"] == "run-1"
    assert "waited" not in calls


async def test_upload_file_via_cdp_rejects_missing_file(tmp_path) -> None:
    with pytest.raises(RuntimeError):
        await browser_tools.upload_file_via_cdp(
            object(), object(), 'input[type="file"]', str(tmp_path / "missing.pdf")
        )
