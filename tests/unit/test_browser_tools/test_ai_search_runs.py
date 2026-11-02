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


async def test_run_task1_repeats_search_when_ai_click_navigates(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)

    def _navigate() -> None:
        page.current_url = "https://www.linkedin.com/jobs/ai-search/"

    ai_button = FakeElement(
        "Try AI job search",
        on_click=_navigate,
        click_error=RuntimeError("Execution context was destroyed"),
    )
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

    assert outcome.ai_job_search_clicked is True
    assert calls == ["software engineer", "software engineer"]
    assert outcome.easy_apply_filter_selected is True


async def test_run_task1_reclicks_ai_job_search_while_it_reappears(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)
    ai_button = FakeElement("Try AI job search")
    filt = _filter_element(page)
    # The button never goes away; the loop must stop at the safety cap.
    page.ai_buttons = [ai_button]
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

    assert outcome.ai_job_search_clicks == browser_tools._MAX_AI_JOB_SEARCH_CLICKS
    # The search runs once initially and once after each AI click.
    assert calls == ["software engineer"] * (1 + browser_tools._MAX_AI_JOB_SEARCH_CLICKS)
    assert outcome.easy_apply_filter_selected is True


async def test_run_task1_stops_reclicking_when_ai_button_disappears(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)
    ai_button = FakeElement("Try AI job search")
    filt = _filter_element(page)
    # Present for two clicks, then gone; the loop stops on its own.
    page.ai_buttons_queue = [[ai_button], [ai_button], []]
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

    assert outcome.ai_job_search_clicks == 2
    assert calls == ["software engineer", "software engineer", "software engineer"]
    assert outcome.easy_apply_filter_selected is True


async def test_run_task1_records_ai_search_candidates_when_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)
    filt = _filter_element(page)
    # No AI control; only search-related controls are visible. Their labels must
    # be recorded so a real-run miss is diagnosable.
    page.ai_buttons = [FakeElement("Save this search"), FakeElement("Search jobs")]
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

    assert outcome.ai_job_search_present is False
    assert outcome.ai_job_search_candidates == ["Save this search", "Search jobs"]
    assert "controls seen" in outcome.notes


async def test_run_task1_does_not_repeat_search_without_ai_button(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)
    filt = _filter_element(page)
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

    async def fake_search(_page, query, _settings):
        calls.append(query)
        return True, 25, SEARCH_URL

    monkeypatch.setattr(linkedin_tools.orchestrator, "open_jobs_search", fake_search)
    monkeypatch.setattr(linkedin_tools.ai_search, "open_jobs_search", fake_search)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert calls == ["software engineer"]
    assert outcome.ai_job_search_clicked is False
    assert outcome.easy_apply_filter_selected is True


async def test_run_task1_succeeds_without_ai_job_search_button(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)
    filt = _filter_element(page)
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

    assert outcome.ai_job_search_present is False
    assert outcome.ai_job_search_clicked is False
    assert outcome.easy_apply_filter_selected is True
    assert outcome.screenshot_path is None
