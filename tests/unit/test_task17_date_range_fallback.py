"""Unit tests for Task 17's Past 24 hours → Past week fallback (no browser)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task2Outcome
from src.tools import linkedin_results_scan as scan_mod
from src.tools.linkedin_apply_loop import _no_job_reason
from src.tools.linkedin_date_posted import (
    PAST_24_HOURS_TPR,
    PAST_24_HOURS_VALUE,
    PAST_WEEK_TPR,
    PAST_WEEK_VALUE,
    with_date_range,
)


def _settings() -> Settings:
    return Settings(
        session=SessionSettings(post_click_wait_seconds=0),
    )


def _scan_result(*, cards_seen: int = 1, selected: bool = False) -> SimpleNamespace:
    return SimpleNamespace(cards_seen=cards_seen, opened=False, selected=selected)


def test_scan_ranges_starts_with_24h_and_widens_to_week() -> None:
    assert scan_mod.scan_ranges(PAST_24_HOURS_VALUE) == (
        (PAST_24_HOURS_VALUE, ""),
        (PAST_WEEK_VALUE, "Past week"),
    )
    # A run already on the week keeps scanning only that range.
    assert scan_mod.scan_ranges(PAST_WEEK_VALUE) == ((PAST_WEEK_VALUE, "Past week"),)
    # An unknown range keeps the legacy single-range behaviour.
    assert scan_mod.scan_ranges("") == ((PAST_24_HOURS_VALUE, ""),)


def test_with_date_range_resets_start_and_preserves_easy_apply() -> None:
    url = (
        "https://www.linkedin.com/jobs/search-results/"
        "?keywords=software+engineer&f_AL=true&f_TPR=r86400&start=25"
    )

    week = with_date_range(url, PAST_WEEK_TPR, reset_start=True)

    assert "f_TPR=r604800" in week
    assert "f_AL=true" in week
    assert "keywords=software+engineer" in week
    assert "start=25" not in week
    assert PAST_24_HOURS_TPR not in week


@pytest.mark.asyncio
async def test_scan_widens_to_week_only_after_24h_is_exhausted(monkeypatch) -> None:
    calls: list[str] = []
    switched: list[bool] = []

    async def scan_page(
        page, settings, notify, outcome, tried, applied_seen, capture, *, open_form=True
    ):
        calls.append(outcome.date_range_used)
        return _scan_result(selected=len(calls) == 2)

    async def no_next(page, settings, notify=None, reason_out=None):
        return False

    async def switch(page, settings, notify):
        switched.append(True)
        return True, ""

    monkeypatch.setattr(scan_mod, "go_to_next_page", no_next)
    monkeypatch.setattr(scan_mod, "switch_to_past_week", switch)

    outcome = Task2Outcome()
    await scan_mod.scan_results_pages(
        object(),
        _settings(),
        lambda _m: None,
        outcome,
        set(),
        set(),
        scan_page,
        open_form=False,
        date_range=PAST_24_HOURS_VALUE,
    )

    assert switched == [True]
    assert calls == [PAST_24_HOURS_VALUE, PAST_WEEK_VALUE]
    assert outcome.date_range_used == PAST_WEEK_VALUE
    assert outcome.date_range_fallback_used is True
    assert outcome.pages_visited == 2
    assert outcome.pages_visited_past_week == 1
    assert outcome.job_selected is False  # scan_page only reports selected


@pytest.mark.asyncio
async def test_scan_does_not_widen_after_a_recoverable_pagination_failure(
    monkeypatch,
) -> None:
    switched: list[bool] = []

    async def scan_page(
        page, settings, notify, outcome, tried, applied_seen, capture, *, open_form=True
    ):
        return _scan_result()

    async def broken_next(page, settings, notify=None, reason_out=None):
        if reason_out is not None:
            reason_out.append("the results list did not change after the click")
        return False

    async def switch(page, settings, notify):  # pragma: no cover - must not run
        switched.append(True)
        return True, ""

    monkeypatch.setattr(scan_mod, "go_to_next_page", broken_next)
    monkeypatch.setattr(scan_mod, "switch_to_past_week", switch)

    outcome = Task2Outcome()
    await scan_mod.scan_results_pages(
        object(),
        _settings(),
        lambda _m: None,
        outcome,
        set(),
        set(),
        scan_page,
        date_range=PAST_24_HOURS_VALUE,
    )

    assert switched == []
    assert outcome.date_range_fallback_used is False
    assert "did not change" in outcome.notes


@pytest.mark.asyncio
async def test_scan_on_the_week_range_does_not_widen_again(monkeypatch) -> None:
    calls: list[str] = []

    async def scan_page(
        page, settings, notify, outcome, tried, applied_seen, capture, *, open_form=True
    ):
        calls.append(outcome.date_range_used)
        return _scan_result(selected=True)

    async def switch(page, settings, notify):  # pragma: no cover - must not run
        raise AssertionError("a week list must not switch ranges again")

    monkeypatch.setattr(scan_mod, "switch_to_past_week", switch)

    outcome = Task2Outcome()
    await scan_mod.scan_results_pages(
        object(),
        _settings(),
        lambda _m: None,
        outcome,
        set(),
        set(),
        scan_page,
        date_range=PAST_WEEK_VALUE,
    )

    assert calls == [PAST_WEEK_VALUE]
    assert outcome.date_range_used == PAST_WEEK_VALUE
    assert outcome.date_range_fallback_used is False
    assert outcome.pages_visited_past_week == 1


@pytest.mark.asyncio
async def test_scan_page_cap_does_not_start_a_new_range(monkeypatch) -> None:
    switched: list[bool] = []

    async def scan_page(
        page, settings, notify, outcome, tried, applied_seen, capture, *, open_form=True
    ):
        return _scan_result()

    async def switch(page, settings, notify):  # pragma: no cover - must not run
        switched.append(True)
        return True, ""

    monkeypatch.setattr(scan_mod, "_MAX_RESULT_PAGES", 1)
    monkeypatch.setattr(scan_mod, "switch_to_past_week", switch)

    outcome = Task2Outcome()
    await scan_mod.scan_results_pages(
        object(),
        _settings(),
        lambda _m: None,
        outcome,
        set(),
        set(),
        scan_page,
        date_range=PAST_24_HOURS_VALUE,
    )

    assert switched == []
    assert outcome.date_range_fallback_used is False
    assert "results-page cap" in outcome.notes


def test_no_job_reason_explains_both_ranges() -> None:
    assert "past 24 hours or the past week" in _no_job_reason(
        Task2Outcome(date_range_fallback_used=True)
    )
    assert "past week" in _no_job_reason(Task2Outcome(date_range_used=PAST_WEEK_VALUE))
