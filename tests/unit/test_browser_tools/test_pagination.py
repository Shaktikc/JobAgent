"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

from src.tools import browser as browser_tools
from src.tools.linkedin import build_jobs_search_url

from .fakes import FakePage
from .helpers import (
    _job_card,
    _settings,
)

SEARCH_URL = build_jobs_search_url("software engineer")


async def test_task2_applied_skip_can_be_disabled(tmp_path) -> None:
    page = FakePage(
        details_apply_labels={0: "Easy Apply to Backend Engineer at Acme"},
    )
    page.by_selector = {
        "li.jobs-search-results__list-item": [
            _job_card(page, 0, "Backend Engineer Acme Applied 5 months ago"),
        ]
    }

    outcome = await browser_tools._task2_on_page(
        page,
        _settings(tmp_path, post_click_wait_seconds=0, skip_applied=False),
        lambda _m: None,
    )

    assert outcome.applied_jobs_skipped == 0
    assert outcome.job_index == 0
    assert outcome.easy_apply_clicked is True
    assert outcome.application_form_opened is True


async def test_task2_paginates_when_a_whole_page_is_applied(tmp_path, monkeypatch) -> None:
    """Task 7: when every card on the page is Applied, the next page is opened
    and Task 6's scan runs again there."""
    import src.tools.linkedin_results_scan as results_scan

    page = FakePage(details_apply_labels={0: "Easy Apply to Data Engineer at Acme"})
    page_one = [
        _job_card(page, 0, "Backend Engineer Acme Applied 5 months ago"),
        _job_card(page, 1, "Frontend Engineer Acme Applied 2 weeks ago"),
    ]
    page_two = [_job_card(page, 0, "Data Engineer Acme Easy Apply")]
    page.by_selector = {"li.jobs-search-results__list-item": page_one}
    calls = {"next": 0}

    async def fake_next(p, settings, notify=None, **_kwargs):
        calls["next"] += 1
        p.by_selector = {"li.jobs-search-results__list-item": page_two}
        return True

    monkeypatch.setattr(results_scan, "go_to_next_page", fake_next)

    outcome = await browser_tools._task2_on_page(
        page, _settings(tmp_path, post_click_wait_seconds=0), lambda _m: None
    )

    assert calls["next"] == 1
    assert outcome.pages_visited == 2
    assert outcome.applied_jobs_skipped == 2
    assert outcome.job_title == "Data Engineer Acme Easy Apply"
    assert outcome.easy_apply_clicked is True
    assert outcome.application_form_opened is True


async def test_task2_stops_after_searching_every_page(tmp_path, monkeypatch) -> None:
    """Task 7: if every job on every page is Applied, nothing is opened and the
    run stops with a clear note (after recording the pages visited)."""
    import src.tools.linkedin_results_scan as results_scan

    page = FakePage()
    page.by_selector = {
        "li.jobs-search-results__list-item": [
            _job_card(page, 0, "Backend Engineer Acme Applied 5 months ago"),
            _job_card(page, 1, "Data Engineer Acme Applied 2 weeks ago"),
        ]
    }
    calls = {"next": 0}

    async def fake_next(p, settings, notify=None, **_kwargs):
        calls["next"] += 1
        if calls["next"] == 1:
            p.by_selector = {
                "li.jobs-search-results__list-item": [
                    _job_card(p, 0, "QA Engineer Acme Applied 1 month ago"),
                    _job_card(p, 1, "DevOps Engineer Acme Applied 3 days ago"),
                ]
            }
            return True
        return False

    monkeypatch.setattr(results_scan, "go_to_next_page", fake_next)

    outcome = await browser_tools._task2_on_page(
        page, _settings(tmp_path, post_click_wait_seconds=0), lambda _m: None
    )

    assert calls["next"] == 2
    assert outcome.pages_visited == 2
    assert outcome.applied_jobs_skipped == 4
    assert outcome.easy_apply_clicked is False
    assert outcome.application_form_opened is False
    assert "no unapplied job found" in outcome.notes
    assert "searched 2 results page(s)" in outcome.notes


async def test_task2_paginates_when_unapplied_cards_have_no_easy_apply(
    tmp_path, monkeypatch
) -> None:
    """A page with unapplied cards but no openable Easy Apply advances.

    Live BUG-063: 21 of 24 cards were Applied and the remaining three had no Easy
    Apply, so the old "only when the whole page is Applied" rule stopped the loop
    without ever checking page 2.
    """
    import src.tools.linkedin_results_scan as results_scan

    page = FakePage()
    page_one = {
        "li.jobs-search-results__list-item": [
            _job_card(page, 0, "Backend Engineer Acme Applied 5 months ago"),
            _job_card(page, 1, "Data Engineer Acme Easy Apply"),
        ]
    }
    page_two = {
        "li.jobs-search-results__list-item": [
            _job_card(page, 0, "QA Engineer Acme Easy Apply"),
        ]
    }
    page.by_selector = page_one
    page.details_apply_labels = {0: "Easy Apply to QA Engineer at Acme"}
    called = {"next": 0}

    async def fake_next(p, settings, notify=None, **_kwargs):
        called["next"] += 1
        p.by_selector = page_two
        return True

    monkeypatch.setattr(results_scan, "go_to_next_page", fake_next)

    outcome = await browser_tools._task2_on_page(
        page, _settings(tmp_path, post_click_wait_seconds=0), lambda _m: None
    )

    assert called["next"] == 1
    assert outcome.pages_visited == 2
    assert outcome.job_title == "QA Engineer Acme Easy Apply"
    assert outcome.easy_apply_clicked is True
    assert outcome.application_form_opened is True


async def test_task2_stops_at_the_results_page_cap(tmp_path, monkeypatch) -> None:
    """Task 7 caps how many pages it will visit, so a control that never
    disables cannot loop forever."""
    import src.tools.linkedin_results_scan as results_scan

    monkeypatch.setattr(results_scan, "_MAX_RESULT_PAGES", 2)
    page = FakePage()
    counter = {"n": 0}

    def _applied_page(p):
        counter["n"] += 1
        title = f"Backend Engineer {counter['n']} Acme Applied 5 months ago"
        return {"li.jobs-search-results__list-item": [_job_card(p, 0, title)]}

    page.by_selector = _applied_page(page)

    async def fake_next(p, settings, notify=None, **_kwargs):
        p.by_selector = _applied_page(p)
        return True

    monkeypatch.setattr(results_scan, "go_to_next_page", fake_next)

    outcome = await browser_tools._task2_on_page(
        page, _settings(tmp_path, post_click_wait_seconds=0), lambda _m: None
    )

    assert outcome.pages_visited == 2
    assert outcome.easy_apply_clicked is False
    assert "results-page cap" in outcome.notes
