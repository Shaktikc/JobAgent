"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

from src.tools import browser as browser_tools
from src.tools.linkedin import build_jobs_search_url

from .fakes import FakeElement, FakePage
from .helpers import (
    _job_card,
    _settings,
)

SEARCH_URL = build_jobs_search_url("software engineer")


async def test_read_job_cards() -> None:
    page = FakePage()
    cards = [_job_card(page, 0, "Backend Engineer"), _job_card(page, 1, "Data Engineer")]
    page.by_selector = {"li.jobs-search-results__list-item": cards}

    assert await browser_tools.read_job_cards(page) == cards
    assert await browser_tools.read_job_cards(FakePage()) == []


async def test_read_job_cards_finds_ai_job_cards() -> None:
    """On the AI/semantic results page the cards are div[role="button"], not
    classic <li> items; read_job_cards marks them and returns them."""
    card = FakeElement("Backend Engineer")
    page = FakePage(ai_job_cards=[card])
    assert await browser_tools.read_job_cards(page) == [card]


async def test_find_job_apply_button_reads_details_pane() -> None:
    page = FakePage(details_apply_labels={2: "Easy Apply to Data Engineer at Acme"})
    page.selected_job = 2

    button, label = await browser_tools.find_job_apply_button(page)
    assert button is not None
    assert label == "Easy Apply to Data Engineer at Acme"


async def test_find_job_apply_button_matches_semantic_layout_label() -> None:
    """The AI/semantic layout's apply button has hashed classes, so it is matched
    by its accessible label ("Easy Apply to this job") rather than a CSS class."""
    page = FakePage(
        by_selector={
            'button[aria-label^="Easy Apply to" i]': [FakeElement("Easy Apply to this job")]
        }
    )

    button, label = await browser_tools.find_job_apply_button(page)

    assert button is not None
    assert label == "Easy Apply to this job"


async def test_find_job_apply_button_none_without_selection() -> None:
    assert await browser_tools.find_job_apply_button(FakePage()) == (None, "")


async def test_find_job_apply_button_fallback_skips_job_cards() -> None:
    """A job card whose text contains "Easy Apply" must not be chosen as the
    apply button when the CSS selectors miss the details pane's button.

    On the AI/semantic results page the job cards are div[role="button"] and their
    accessible text carries the "Easy Apply" badge, so a naive fallback scan picks
    the first card and clicks it instead of the blue "Easy Apply" button (the Task
    2 bug). The fallback must exclude job cards and return the real apply button.
    """
    card = FakeElement(
        "Senior Software Engineer (Founding Team) Care GP Sydney, NSW (On-site) "
        "Actively reviewing applicants Easy Apply",
        aria_label=False,
    )
    apply_button = FakeElement("Easy Apply to Senior Software Engineer at Care GP")
    page = FakePage(by_selector={"button, [role='button']": [card, apply_button]})

    button, label = await browser_tools.find_job_apply_button(page)

    assert button is apply_button
    assert label == "Easy Apply to Senior Software Engineer at Care GP"
    # The job card was never picked as the apply button.
    assert button is not card


async def test_task2_selects_job_and_opens_form(tmp_path) -> None:
    page = FakePage(
        results_count=3,
        details_apply_labels={0: "Easy Apply to Backend Engineer at Acme"},
    )
    page.by_selector = {
        "li.jobs-search-results__list-item": [
            _job_card(page, 0, "Backend Engineer"),
            _job_card(page, 1, "Data Engineer"),
        ]
    }

    outcome = await browser_tools._task2_on_page(
        page, _settings(tmp_path, post_click_wait_seconds=0), lambda _m: None
    )

    assert outcome.jobs_seen == 2
    assert outcome.job_index == 0
    assert outcome.job_title == "Backend Engineer"
    assert outcome.skipped_jobs == 0
    assert outcome.easy_apply_button_found is True
    assert outcome.easy_apply_clicked is True
    assert outcome.application_form_opened is True


async def test_task2_match_first_selects_without_clicking_easy_apply(tmp_path) -> None:
    """Task 16: an unmatched job is selected and read without opening the form."""
    from src.tools.linkedin_best_matching_resume import read_job_description

    page = FakePage(
        results_count=1,
        details_apply_labels={0: "Easy Apply to Backend Engineer at Acme"},
    )
    page.by_selector = {
        "li.jobs-search-results__list-item": [_job_card(page, 0, "Backend Engineer")]
    }

    outcome = await browser_tools._task2_on_page(
        page,
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
        capture=read_job_description,
        open_form=False,
    )

    assert outcome.job_selected is True
    assert outcome.easy_apply_button_found is True
    assert outcome.easy_apply_clicked is False
    assert outcome.application_form_opened is False
    assert page.modal_open is False, "Easy Apply was clicked before the resume match"
    assert outcome.job_description is not None
    assert outcome.job_description.is_read is True


async def test_task2_captures_the_description_before_easy_apply(tmp_path) -> None:
    """Task 3's description is read while the job view is intact, before Easy Apply.

    On LinkedIn's newer inline Easy Apply form the job view can be replaced, so the
    read must happen before the apply click (regression for the empty description
    that made the LLM answer "none").
    """
    from src.tools.linkedin_best_matching_resume import read_job_description

    page = FakePage(
        results_count=1,
        details_apply_labels={0: "Easy Apply to Backend Engineer at Acme"},
    )
    page.by_selector = {
        "li.jobs-search-results__list-item": [_job_card(page, 0, "Backend Engineer")]
    }
    seen: list[bool] = []

    async def capture(p):
        seen.append(page.modal_open)  # the form must not be open yet
        return await read_job_description(p)

    outcome = await browser_tools._task2_on_page(
        page, _settings(tmp_path), lambda _m: None, capture=capture
    )

    assert outcome.job_description is not None
    assert outcome.job_description.is_read is True
    assert outcome.job_description.title == "Backend Engineer"
    assert seen == [False]  # read before the Easy Apply modal opened


async def test_task2_skips_jobs_without_easy_apply(tmp_path) -> None:
    page = FakePage(
        details_apply_labels={0: "Apply on company website", 1: "Apply"},
    )
    page.by_selector = {
        "li.jobs-search-results__list-item": [
            _job_card(page, 0, "External A"),
            _job_card(page, 1, "External B"),
        ]
    }

    outcome = await browser_tools._task2_on_page(
        page, _settings(tmp_path, post_click_wait_seconds=0), lambda _m: None
    )

    assert outcome.skipped_jobs == 2
    assert outcome.easy_apply_button_found is False
    assert outcome.easy_apply_clicked is False
    assert outcome.application_form_opened is False


async def test_task2_reports_when_form_does_not_open(tmp_path) -> None:
    page = FakePage(
        details_apply_labels={0: "Easy Apply to Backend Engineer at Acme"},
        apply_opens_modal=False,
    )
    page.by_selector = {"li.jobs-search-results__list-item": [_job_card(page, 0, "Backend")]}

    outcome = await browser_tools._task2_on_page(
        page,
        _settings(tmp_path, post_click_wait_seconds=0, easy_apply_timeout_seconds=0.05),
        lambda _m: None,
    )

    assert outcome.easy_apply_clicked is True
    assert outcome.application_form_opened is False
    assert outcome.notes


async def test_task2_skips_applied_jobs_and_opens_first_unapplied(tmp_path) -> None:
    page = FakePage(
        details_apply_labels={1: "Easy Apply to Data Engineer at Acme"},
    )
    page.by_selector = {
        "li.jobs-search-results__list-item": [
            _job_card(page, 0, "Backend Engineer Acme Applied 5 months ago"),
            _job_card(page, 1, "Data Engineer Acme Easy Apply"),
        ]
    }

    outcome = await browser_tools._task2_on_page(
        page, _settings(tmp_path, post_click_wait_seconds=0), lambda _m: None
    )

    # The applied card is never clicked (no application form opened for it).
    assert page.selected_job == 1
    assert outcome.applied_jobs_skipped == 1
    assert outcome.applied_skipped_cards == [
        {"index": 0, "title": "Backend Engineer Acme Applied 5 months ago"}
    ]
    assert outcome.job_index == 1
    assert outcome.job_title == "Data Engineer Acme Easy Apply"
    assert outcome.easy_apply_clicked is True
    assert outcome.application_form_opened is True


async def test_task2_stops_when_every_card_is_applied(tmp_path) -> None:
    page = FakePage()
    page.by_selector = {
        "li.jobs-search-results__list-item": [
            _job_card(page, 0, "Backend Engineer Acme Applied 5 months ago"),
            _job_card(page, 1, "Data Engineer Acme Applied 2 weeks ago"),
        ]
    }

    outcome = await browser_tools._task2_on_page(
        page, _settings(tmp_path, post_click_wait_seconds=0), lambda _m: None
    )

    assert page.selected_job is None
    assert outcome.applied_jobs_skipped == 2
    assert outcome.easy_apply_clicked is False
    assert outcome.application_form_opened is False
    assert outcome.job_index is None
    assert "no unapplied job found" in outcome.notes


async def test_read_job_description() -> None:
    page = FakePage()
    description = await browser_tools.read_job_description(page)

    assert description.title == "Backend Engineer"
    assert description.company == "Acme"
    assert description.location == "Remote"
    assert "Python" in description.body
    assert description.page_url == "https://www.linkedin.com/jobs/view/1"
    assert description.is_read is True


async def test_read_job_description_empty_when_pane_missing() -> None:
    page = FakePage(job_description={"title": "", "company": "", "location": "", "body": ""})
    description = await browser_tools.read_job_description(page)
    assert description.is_read is False
