"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

import pytest

from src.tools import browser as browser_tools
from src.tools import linkedin_search as linkedin_tools
from src.tools.linkedin import build_jobs_search_url

from .fakes import FakeElement, FakePage
from .helpers import (
    _APPLY_BUTTON_CLASS,
    _FILTER_PILL_CLASS,
    _filter_element,
    _settings,
)

SEARCH_URL = build_jobs_search_url("software engineer")


async def test_find_easy_apply_filter_prefers_filter_label() -> None:
    job_button = FakeElement("Easy Apply to Backend Engineer at Acme")
    filter_button = FakeElement("Easy Apply filter.")
    page = FakePage(by_selector={"button[aria-label*='Easy Apply']": [job_button, filter_button]})
    # Both match `*='Easy Apply'`; the filter must win over the job's button.
    assert await browser_tools.find_easy_apply_filter(page) is filter_button


async def test_find_easy_apply_filter_prefers_toggle_pill_over_apply_button() -> None:
    """The filter pill and the blue apply button share the label "Easy Apply".

    From the real page: the pill is role="radio" with aria-checked (id
    searchFilter_applyWithLinkedin, class search-reusables__filter-pill-button);
    the blue button is jobs-apply-button / artdeco-button--primary. Only the pill
    is a choice toggle, so it must win even though it appears after the apply
    button and its label is just "Easy Apply filter.".
    """
    apply_btn = FakeElement(
        "Easy Apply to Senior Software Engineer at Care GP",
        aria_label=False,
        css_class="jobs-apply-button artdeco-button artdeco-button--primary ember-view",
        data_live_test=True,
    )
    pill = FakeElement(
        "Easy Apply filter.",
        css_class=_FILTER_PILL_CLASS,
        aria_checked="false",
    )
    page = FakePage(
        by_selector={
            "button, [role='button']": [apply_btn, pill],
            "button[aria-label*='Easy Apply']": [apply_btn, pill],
        }
    )
    assert await browser_tools.find_easy_apply_filter(page) is pill


async def test_find_easy_apply_filter_from_real_linkedin_dom() -> None:
    """Regression test built from the real captured LinkedIn DOM.

    The filter pill (role="radio", aria-checked, id searchFilter_applyWithLinkedin)
    must be selected and the two blue jobs-apply-button controls skipped, even
    though all three mention "Easy Apply".
    """
    apply_top = FakeElement(
        "Easy Apply to Programmer (Unity) at True Anomaly Entertainment",
        css_class=_APPLY_BUTTON_CLASS,
        data_live_test=True,
    )
    apply_sticky = FakeElement(
        "Easy Apply to Programmer (Unity) at True Anomaly Entertainment",
        css_class=_APPLY_BUTTON_CLASS,
        data_live_test=True,
    )
    filter_pill = FakeElement(
        "Easy Apply filter.",
        css_class=_FILTER_PILL_CLASS,
        aria_checked="false",
    )
    page = FakePage(
        by_selector={
            "button, [role='button']": [apply_top, apply_sticky, filter_pill],
            "button[aria-label*='Easy Apply']": [apply_top, apply_sticky, filter_pill],
        }
    )
    assert await browser_tools.find_easy_apply_filter(page) is filter_pill


async def test_find_easy_apply_filter_never_returns_the_apply_button() -> None:
    """A lone blue apply button (no filter toggle) must not be returned as the filter."""
    apply_btn = FakeElement(
        "Easy Apply",
        aria_label=False,
        css_class="jobs-apply-button artdeco-button artdeco-button--primary",
        data_live_test=True,
    )
    page = FakePage(by_selector={"button, [role='button']": [apply_btn]})
    assert await browser_tools.find_easy_apply_filter(page) is None


async def test_find_easy_apply_filter_skips_apply_button_by_class() -> None:
    """The blue apply button is skipped by its jobs-apply-button class, so a
    bare-label Easy Apply filter pill (without a toggle attribute) still wins by
    its 'filter' name."""
    apply_btn = FakeElement(
        "Easy Apply",
        aria_label=False,
        css_class="jobs-apply-button artdeco-button artdeco-button--primary",
        data_live_test=True,
    )
    pill = FakeElement("Easy Apply filter.")
    page = FakePage(by_selector={"button, [role='button']": [apply_btn, pill]})
    assert await browser_tools.find_easy_apply_filter(page) is pill


async def test_find_easy_apply_filter_prefers_known_selector() -> None:
    filt = FakeElement("Easy Apply filter.")
    page = FakePage(by_selector={"button[aria-label*='Easy Apply']": [filt]})
    assert await browser_tools.find_easy_apply_filter(page) is filt


async def test_find_easy_apply_filter_none_when_absent() -> None:
    page = FakePage(
        by_selector={"button, [role='button']": [FakeElement("Save"), FakeElement("Date posted")]}
    )
    assert await browser_tools.find_easy_apply_filter(page) is None


async def test_select_easy_apply_filter_clicks(tmp_path) -> None:
    page = FakePage()
    filt = _filter_element(page)
    page.by_selector = {"button[aria-label*='Easy Apply']": [filt]}

    selected, note = await browser_tools.select_easy_apply_filter(
        page, _settings(tmp_path, post_click_wait_seconds=0)
    )
    assert selected is True
    assert note == ""
    assert filt.clicked is True


async def test_select_easy_apply_filter_waits_for_the_page_to_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Clicking the filter re-renders the results page, so the run must wait for
    the page to load before verifying or moving on to the next control."""
    page = FakePage()
    filt = _filter_element(page)
    page.by_selector = {"button[aria-label*='Easy Apply']": [filt]}
    waits: list[float] = []

    async def fake_wait(_page, timeout_seconds):
        waits.append(timeout_seconds)
        return True

    monkeypatch.setattr(linkedin_tools.common, "_wait_for_load", fake_wait)

    selected, _note = await browser_tools.select_easy_apply_filter(
        page, _settings(tmp_path, post_click_wait_seconds=0)
    )

    assert selected is True
    assert filt.clicked is True
    assert waits


async def test_select_easy_apply_filter_falls_back_to_url(tmp_path) -> None:
    page = FakePage(filter_selected=False)
    page.current_url = SEARCH_URL
    # No filter control in the DOM, so the f_AL=true fallback must be used.
    selected, _ = await browser_tools.select_easy_apply_filter(
        page, _settings(tmp_path, post_click_wait_seconds=0)
    )
    assert selected is True
    assert any("f_AL=true" in url for url in page.goto_calls)
