"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

import pytest

from src.state import DEFAULT_LOGIN_URL
from src.tools import browser as browser_tools
from src.tools import linkedin_search as linkedin_tools
from src.tools.linkedin import build_jobs_search_url

from .fakes import FakeElement, FakePage, FakeSession
from .helpers import (
    _filter_element,
    _settings,
)

SEARCH_URL = build_jobs_search_url("software engineer")


async def test_find_ai_job_search_button_present() -> None:
    button = FakeElement("Try AI job search")
    page = FakePage(ai_buttons=[FakeElement("Save this search"), button])
    # The first candidate merely mentions "search"; the AI one must win.
    assert await browser_tools.find_ai_job_search_button(page) is button


async def test_find_ai_job_search_button_absent() -> None:
    page = FakePage(
        ai_buttons=[FakeElement("Save this search"), FakeElement("Search jobs")]
    )
    assert await browser_tools.find_ai_job_search_button(page) is None


async def test_ai_job_search_query_scans_varied_markup() -> None:
    # The runtime scan must not rely on a plain <button>: LinkedIn may render the
    # entry point as a link/role=button/role=link, with its label spread across
    # aria-label, visible text, value, or title.
    query = browser_tools._AI_CANDIDATES_QUERY
    assert 'role="link"' in query
    assert 'role="button"' in query
    assert "aria-label" in query
    assert "innerText" in query
    assert "value" in query


async def test_click_ai_job_search_clicks_when_present(tmp_path) -> None:
    button = FakeElement("Try AI job search")
    page = FakePage(ai_buttons=[button])

    clicked = await browser_tools.click_ai_job_search(
        page, _settings(tmp_path, post_click_wait_seconds=0)
    )

    assert clicked is True
    assert button.clicked is True
    assert button.scrolled is True


async def test_click_ai_job_search_returns_false_when_absent(tmp_path) -> None:
    page = FakePage()
    clicked = await browser_tools.click_ai_job_search(
        page, _settings(tmp_path, post_click_wait_seconds=0)
    )
    assert clicked is False


async def test_click_ai_job_search_treats_navigation_as_clicked(tmp_path) -> None:
    page = FakePage()

    def _navigate() -> None:
        page.current_url = "https://www.linkedin.com/jobs/ai-search/"

    # A click that navigates can raise *after* the navigation already started
    # (the CDP execution context is destroyed). It must still count as clicked.
    button = FakeElement(
        "Try AI job search",
        on_click=_navigate,
        click_error=RuntimeError("Execution context was destroyed"),
    )
    page.ai_buttons = [button]

    clicked = await browser_tools.click_ai_job_search(
        page, _settings(tmp_path, post_click_wait_seconds=0)
    )

    assert clicked is True
    assert button.clicked is True
    assert page.current_url == "https://www.linkedin.com/jobs/ai-search/"


async def test_click_ai_job_search_waits_for_the_page_to_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage()
    page.ai_buttons = [FakeElement("Try AI job search")]

    waits: list[float] = []

    async def fake_wait(_page, timeout_seconds):
        waits.append(timeout_seconds)
        return True

    monkeypatch.setattr(linkedin_tools.ai_search, "_wait_for_load", fake_wait)

    clicked = await browser_tools.click_ai_job_search(
        page, _settings(tmp_path, post_click_wait_seconds=0)
    )

    assert clicked is True
    # The click may navigate/reload, so the page load must be awaited after it.
    assert waits


async def test_wait_for_ai_job_search_button_finds_late_button(tmp_path) -> None:
    late = FakeElement("Try AI job search")
    # Nothing on the first scan; the button renders on a later poll.
    page = FakePage(ai_buttons_queue=[[], [late]])

    button = await browser_tools.wait_for_ai_job_search_button(
        page, _settings(tmp_path, ai_search_timeout_seconds=2.0)
    )

    assert button is late


async def test_wait_for_ai_job_search_button_times_out(tmp_path) -> None:
    page = FakePage(ai_buttons=[])

    button = await browser_tools.wait_for_ai_job_search_button(
        page, _settings(tmp_path, ai_search_timeout_seconds=0.05)
    )
    assert button is None


async def test_run_task1_clicks_try_ai_job_search_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)
    ai_button = FakeElement("Try AI job search")
    filt = _filter_element(page)
    # The button is present once, then gone after the click; click it once.
    page.ai_buttons_queue = [[ai_button], []]
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [filt],
    }
    session = FakeSession(page)
    monkeypatch.setattr(linkedin_tools.orchestrator, "build_browser", lambda settings: session)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert outcome.ai_job_search_present is True
    assert outcome.ai_job_search_clicked is True
    assert outcome.ai_job_search_clicks == 1
    assert ai_button.clicked is True
    assert outcome.easy_apply_filter_selected is True
    assert outcome.screenshot_path is None


async def test_run_task1_repeats_search_after_ai_job_search(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)
    ai_button = FakeElement("Try AI job search")
    filt = _filter_element(page)
    page.ai_buttons_queue = [[ai_button], []]
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [filt],
    }
    session = FakeSession(page)
    monkeypatch.setattr(linkedin_tools.orchestrator, "build_browser", lambda settings: session)

    calls: list[str] = []

    async def fake_search(_page, query, _settings, **_kwargs):
        calls.append(query)
        return True, 25, SEARCH_URL

    monkeypatch.setattr(linkedin_tools.orchestrator, "open_jobs_search", fake_search)
    monkeypatch.setattr(linkedin_tools.ai_search, "open_jobs_search", fake_search)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert ai_button.clicked is True
    # The search is performed once, then again after the AI job search click.
    assert calls == ["software engineer", "software engineer"]
    assert outcome.results_found is True
    assert outcome.easy_apply_filter_selected is True


async def test_run_task1_stays_in_ai_mode_when_repeat_returns_no_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """After "Try AI job search" is clicked, never fall back to the classic search.

    LinkedIn's AI mode can render no job cards; a repeat search that returns
    nothing simply ends the re-click loop and the outcome reflects the AI search.
    The classic "software engineer" URL must not be opened again.
    """
    page = FakePage(results_count=14)
    ai_button = FakeElement("Try AI job search")
    filt = _filter_element(page)
    page.ai_buttons_queue = [[ai_button], []]
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [filt],
    }
    session = FakeSession(page)
    monkeypatch.setattr(linkedin_tools.orchestrator, "build_browser", lambda settings: session)

    calls: list[str] = []

    async def fake_search(_page, query, _settings, **_kwargs):
        calls.append(query)
        if len(calls) == 1:
            return True, 14, SEARCH_URL
        # The AI mode page the click left behind has no job cards.
        return (
            False,
            0,
            "https://www.linkedin.com/jobs/search-results/?origin=SEMANTIC_SEARCH_MODE_FROM_CLASSIC",
        )

    monkeypatch.setattr(linkedin_tools.orchestrator, "open_jobs_search", fake_search)
    monkeypatch.setattr(linkedin_tools.ai_search, "open_jobs_search", fake_search)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert outcome.ai_job_search_clicked is True
    # The initial search plus exactly one repeat; the loop stops there.
    assert calls == ["software engineer", "software engineer"]
    # No fallback to the classic search URL; the outcome reflects the AI mode.
    assert SEARCH_URL not in page.goto_calls
    assert outcome.results_found is False
    assert outcome.results_count == 0
