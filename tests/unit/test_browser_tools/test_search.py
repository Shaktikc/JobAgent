"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

import pytest

from src.tools import browser as browser_tools
from src.tools import linkedin_search as linkedin_tools
from src.tools.linkedin import build_jobs_search_url

from .fakes import FakeElement, FakePage
from .helpers import (
    _settings,
)

SEARCH_URL = build_jobs_search_url("software engineer")


async def test_is_logged_in_uses_path() -> None:
    logged_in = FakePage(login_payload={"path": "/feed/", "nav": False, "loginForm": False})
    assert await browser_tools.is_logged_in(logged_in) is True

    on_login = FakePage(login_payload={"path": "/login", "nav": False, "loginForm": True})
    assert await browser_tools.is_logged_in(on_login) is False


async def test_is_logged_in_falls_back_to_nav_on_ambiguous_path() -> None:
    nav = FakePage(login_payload={"path": "/", "nav": True, "loginForm": False})
    assert await browser_tools.is_logged_in(nav) is True

    no_nav = FakePage(login_payload={"path": "/", "nav": False, "loginForm": False})
    assert await browser_tools.is_logged_in(no_nav) is False


async def test_wait_for_login_succeeds_after_user_logs_in() -> None:
    states = ["/login", "/login", "/feed/"]

    def payload():
        return {"path": states.pop(0) if states else "/feed/", "nav": False, "loginForm": False}

    page = FakePage(login_payload=payload)
    assert await browser_tools.wait_for_login(page, timeout_seconds=2, poll_seconds=0.01) is True


async def test_wait_for_login_times_out() -> None:
    page = FakePage(login_payload={"path": "/login", "nav": False, "loginForm": True})
    assert (
        await browser_tools.wait_for_login(page, timeout_seconds=0.05, poll_seconds=0.01) is False
    )


async def test_results_count() -> None:
    assert await browser_tools.results_count(FakePage(results_count=0)) == 0
    assert await browser_tools.results_count(FakePage(results_count=12)) == 12


async def test_results_count_counts_ai_job_cards() -> None:
    """The AI/semantic results page has no classic <li> cards, so results_count
    falls back to counting the div[role="button"] job cards it marks."""
    card = FakeElement("Backend Engineer")
    page = FakePage(results_count=0, ai_job_cards=[card])
    assert await browser_tools.results_count(page) == 1


async def test_type_jobs_search_types_and_submits(tmp_path) -> None:
    field = FakeElement("Search by title, skill, or company")
    submit = FakeElement("Search")
    page = FakePage(
        by_selector={
            "input.jobs-search-box__keyboard-text-input": [field],
            "button.jobs-search-box__submit-button": [submit],
        }
    )
    typed = await browser_tools.type_jobs_search(page, "software engineer", _settings(tmp_path))

    assert typed is True
    assert field.filled == "software engineer"
    assert submit.clicked is True
    # The search bar is already on the page, so the Jobs tab is not reopened.
    assert page.goto_calls == []


async def test_type_jobs_search_waits_for_the_page_to_load_after_submitting(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Only one control may be clicked per page load: after submitting the
    search the run must wait for the page to finish loading before the caller
    reads results or clicks another control (the "many buttons clicked at once"
    bug)."""
    field = FakeElement("Search by title, skill, or company")
    submit = FakeElement("Search")
    page = FakePage(
        by_selector={
            "input.jobs-search-box__keyboard-text-input": [field],
            "button.jobs-search-box__submit-button": [submit],
        }
    )
    waits: list[float] = []

    async def fake_wait(_page, timeout_seconds):
        waits.append(timeout_seconds)
        return True

    monkeypatch.setattr(linkedin_tools.common, "_wait_for_load", fake_wait)

    typed = await browser_tools.type_jobs_search(page, "software engineer", _settings(tmp_path))

    assert typed is True
    assert submit.clicked is True
    # Submitting the search navigates/reloads, so the page load must be awaited.
    assert waits


async def test_type_jobs_search_opens_jobs_tab_only_when_search_bar_absent(tmp_path) -> None:
    page = FakePage()
    typed = await browser_tools.type_jobs_search(page, "software engineer", _settings(tmp_path))

    assert typed is False
    # Without a search bar the Jobs tab is opened once to get one.
    assert page.goto_calls == [browser_tools._JOBS_TAB_URL]


async def test_type_jobs_search_uses_enter_without_submit_button(tmp_path) -> None:
    field = FakeElement("Search by title, skill, or company")
    page = FakePage(by_selector={"input.jobs-search-box__keyboard-text-input": [field]})
    typed = await browser_tools.type_jobs_search(page, "software engineer", _settings(tmp_path))

    assert typed is True
    assert field.filled == "software engineer"
    assert page.pressed == ["Enter"]


async def test_type_jobs_search_types_into_ai_prompt_and_submits(tmp_path) -> None:
    # The AI job search page's prompt is not the standard jobs search bar; it must
    # still be recognised and typed into.
    ai_prompt = FakeElement("Describe the job you want")
    page = FakePage(by_selector={"input": [ai_prompt]})

    typed = await browser_tools.type_jobs_search(page, "software engineer", _settings(tmp_path))

    assert typed is True
    assert ai_prompt.filled == "software engineer"
    assert page.pressed == ["Enter"]
    assert page.goto_calls == []


async def test_find_jobs_search_input_matches_ai_prompt() -> None:
    ai_prompt = FakeElement("Describe the job you want")
    page = FakePage(by_selector={"input": [FakeElement("City"), ai_prompt]})
    assert await browser_tools.find_jobs_search_input(page) is ai_prompt


async def test_type_jobs_search_returns_false_without_search_bar(tmp_path) -> None:
    page = FakePage()
    assert await browser_tools.type_jobs_search(page, "x", _settings(tmp_path)) is False


async def test_find_jobs_search_input_by_label_fallback() -> None:
    labelled = FakeElement("Search by title, skill, or company")
    page = FakePage(by_selector={"input": [FakeElement("City"), labelled]})
    assert await browser_tools.find_jobs_search_input(page) is labelled


async def test_open_jobs_search_types_then_reports_results(tmp_path) -> None:
    field = FakeElement("Search by title, skill, or company")
    page = FakePage(
        by_selector={"input.jobs-search-box__keyboard-text-input": [field]},
        results_count=7,
    )
    found, count, _url = await browser_tools.open_jobs_search(
        page, "software engineer", _settings(tmp_path)
    )
    assert (found, count) == (True, 7)
    assert field.filled == "software engineer"
    # The typed path must not navigate straight to the search URL.
    assert SEARCH_URL not in page.goto_calls


async def test_open_jobs_search_falls_back_to_url_without_search_bar(tmp_path) -> None:
    page = FakePage(results_count=4)
    found, count, url = await browser_tools.open_jobs_search(
        page, "software engineer", _settings(tmp_path)
    )
    assert (found, count) == (True, 4)
    assert url == SEARCH_URL
    assert SEARCH_URL in page.goto_calls


async def test_open_jobs_search_detects_ai_job_cards_promptly(tmp_path) -> None:
    """On the AI/semantic results page the classic <li> cards are absent but the
    div[role="button"] job cards are present. results_count must find them so the
    run does not wait for cards the classic selectors cannot see."""
    field = FakeElement("Search by title, skill, or company")
    card = FakeElement("Backend Engineer")
    page = FakePage(
        by_selector={"input.jobs-search-box__keyboard-text-input": [field]},
        results_count=0,
        ai_job_cards=[card],
    )
    found, count, _url = await browser_tools.open_jobs_search(
        page, "software engineer", _settings(tmp_path)
    )
    assert (found, count) == (True, 1)
    assert field.filled == "software engineer"
    assert SEARCH_URL not in page.goto_calls
