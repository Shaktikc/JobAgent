"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.state import DEFAULT_LOGIN_URL
from src.tools import browser as browser_tools
from src.tools import linkedin_search as linkedin_tools
from src.tools.browser import orchestration
from src.tools.linkedin import build_jobs_search_url

from .fakes import FakeElement, FakePage, FakeSession
from .helpers import (
    _filter_element,
    _job_card,
    _settings,
)

SEARCH_URL = build_jobs_search_url("software engineer")


async def test_run_task1_success(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    page = FakePage(results_count=25)
    filt = _filter_element(page)
    search_field = FakeElement("Search by title, skill, or company")
    submit = FakeElement("Search")
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [search_field],
        "button.jobs-search-box__submit-button": [submit],
        "button[aria-label*='Easy Apply']": [filt],
    }
    session = FakeSession(page)
    messages: list[str] = []

    monkeypatch.setattr(linkedin_tools.orchestrator, "build_browser", lambda settings: session)
    settings = _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL, "software engineer", settings, progress=messages.append
    )

    assert outcome.already_logged_in is True
    assert outcome.logged_in is True
    assert outcome.search_performed is True
    assert outcome.results_found is True
    assert outcome.results_count == 25
    assert outcome.easy_apply_filter_selected is True
    assert outcome.screenshot_path is None
    assert page.goto_calls[0] == DEFAULT_LOGIN_URL
    # The search bar is already present, so the Jobs tab is not reopened.
    assert browser_tools._JOBS_TAB_URL not in page.goto_calls
    assert search_field.filled == "software engineer"
    assert submit.clicked is True
    assert session.started is True and session.killed is False
    assert messages  # progress was reported


async def test_run_task1_paces_each_step_when_step_delay_is_set(
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

    paced: list[float] = []

    async def fake_pace(settings):
        paced.append(settings.session.step_delay_seconds)

    monkeypatch.setattr(linkedin_tools.orchestrator, "_pace", fake_pace)
    monkeypatch.setattr(linkedin_tools.search_box, "_pace", fake_pace)
    monkeypatch.setattr(linkedin_tools.easy_apply_filter, "_pace", fake_pace)
    monkeypatch.setattr(linkedin_tools.ai_search, "_pace", fake_pace)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, step_delay_seconds=0.5, post_click_wait_seconds=0),
    )

    assert outcome.easy_apply_filter_selected is True
    # Every visible step is paced so a human can follow the run.
    assert paced
    assert all(delay == 0.5 for delay in paced)


async def test_run_task1_captures_screenshot_when_login_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(login_payload={"path": "/login", "nav": False, "loginForm": True})
    session = FakeSession(page)

    monkeypatch.setattr(linkedin_tools.orchestrator, "build_browser", lambda settings: session)

    async def fake_wait(_page, *, timeout_seconds, poll_seconds):
        return False

    monkeypatch.setattr(linkedin_tools.orchestrator, "wait_for_login", fake_wait)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL, "software engineer", _settings(tmp_path)
    )

    assert outcome.logged_in is False
    assert outcome.search_performed is False
    assert outcome.screenshot_path is not None
    assert Path(outcome.screenshot_path).is_file()
    assert session.killed is False


async def test_run_task1_captures_screenshot_when_search_is_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=0)
    session = FakeSession(page)

    monkeypatch.setattr(linkedin_tools.orchestrator, "build_browser", lambda settings: session)

    async def fake_search(_page, _query, _settings):
        return False, 0, SEARCH_URL

    monkeypatch.setattr(linkedin_tools.orchestrator, "open_jobs_search", fake_search)
    monkeypatch.setattr(linkedin_tools.ai_search, "open_jobs_search", fake_search)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL, "software engineer", _settings(tmp_path)
    )

    assert outcome.logged_in is True
    assert outcome.search_performed is True
    assert outcome.results_found is False
    assert outcome.easy_apply_filter_selected is False
    assert outcome.screenshot_path is not None
    assert session.killed is False


async def test_run_agent_runs_both_tasks(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
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
    monkeypatch.setattr(orchestration, "build_browser", lambda settings: session)

    result = await browser_tools.run_agent(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert result.task1.logged_in is True
    assert result.task1.easy_apply_filter_selected is True
    assert result.task2.job_title == "Backend Engineer"
    assert result.task2.easy_apply_clicked is True
    assert result.task2.application_form_opened is True
    assert result.task2.screenshot_path is None
    assert result.job_description.title == "Backend Engineer"
    assert session.started is True and session.killed is False


async def test_run_agent_skips_task2_when_task1_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(login_payload={"path": "/login", "nav": False, "loginForm": True})
    session = FakeSession(page)
    monkeypatch.setattr(orchestration, "build_browser", lambda settings: session)

    async def fake_wait(_page, *, timeout_seconds, poll_seconds):
        return False

    monkeypatch.setattr(linkedin_tools.orchestrator, "wait_for_login", fake_wait)

    result = await browser_tools.run_agent(
        DEFAULT_LOGIN_URL, "software engineer", _settings(tmp_path)
    )

    assert result.task1.logged_in is False
    assert result.task2.easy_apply_clicked is False
    assert "skipped" in result.task2.notes.lower()
    assert result.task1.screenshot_path is not None
    assert session.killed is False


async def test_run_agent_captures_screenshot_when_apply_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=5, details_apply_labels={0: "Apply on company website"})
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [_filter_element(page)],
        "li.jobs-search-results__list-item": [_job_card(page, 0, "External Job")],
    }
    session = FakeSession(page)
    monkeypatch.setattr(orchestration, "build_browser", lambda settings: session)

    result = await browser_tools.run_agent(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert result.task1.easy_apply_filter_selected is True
    assert result.task2.easy_apply_clicked is False
    assert result.task2.screenshot_path is not None
    assert session.killed is False
