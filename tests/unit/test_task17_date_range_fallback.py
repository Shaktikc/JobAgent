"""Unit tests for Task 17's two-way date-range fallback (no browser).

The user chooses the primary range at startup. The scan then falls back once:

* Past 24 hours → Past week
* Past week → Past 24 hours
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task2Outcome
from src.tools import linkedin_date_range_fallback as fallback_mod
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


def test_scan_ranges_follows_the_users_startup_choice() -> None:
    week = (PAST_WEEK_VALUE, "Past week")
    day = (PAST_24_HOURS_VALUE, "")

    # 24 hours first → week fallback.
    assert scan_mod.scan_ranges(PAST_24_HOURS_VALUE, PAST_24_HOURS_VALUE) == (day, week)
    # Week first → 24 hours fallback.
    assert scan_mod.scan_ranges(PAST_WEEK_VALUE, PAST_WEEK_VALUE) == (week, day)
    # The week list contains the 24-hour jobs, so a later pass already on the
    # fallback range stays there rather than bouncing back.
    assert scan_mod.scan_ranges(PAST_24_HOURS_VALUE, PAST_WEEK_VALUE) == (day,)
    assert scan_mod.scan_ranges(PAST_WEEK_VALUE, PAST_24_HOURS_VALUE) == (week,)
    # An empty current range starts at the user's choice.
    assert scan_mod.scan_ranges("", PAST_WEEK_VALUE) == (week, day)
    assert scan_mod.scan_ranges("", PAST_24_HOURS_VALUE) == (day, week)


def test_scan_ranges_keeps_the_legacy_behaviour_without_a_preference() -> None:
    # A caller that only knows the current range keeps the original Task 17
    # behaviour: a 24-hour list widens once; a week list does not.
    assert scan_mod.scan_ranges(PAST_24_HOURS_VALUE) == (
        (PAST_24_HOURS_VALUE, ""),
        (PAST_WEEK_VALUE, "Past week"),
    )
    assert scan_mod.scan_ranges(PAST_WEEK_VALUE) == ((PAST_WEEK_VALUE, "Past week"),)
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
    switched: list[str] = []

    async def scan_page(
        page, settings, notify, outcome, tried, applied_seen, capture, *, open_form=True
    ):
        calls.append(outcome.date_range_used)
        return _scan_result(selected=len(calls) == 2)

    async def no_next(page, settings, notify=None, reason_out=None):
        return False

    async def switch(page, settings, value, notify):
        switched.append(value)
        return True, ""

    monkeypatch.setattr(scan_mod, "go_to_next_page", no_next)
    monkeypatch.setattr(scan_mod, "switch_to_date_range", switch)

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
        preferred_range=PAST_24_HOURS_VALUE,
    )

    assert switched == [PAST_WEEK_VALUE]
    assert calls == [PAST_24_HOURS_VALUE, PAST_WEEK_VALUE]
    assert outcome.date_range_preferred == PAST_24_HOURS_VALUE
    assert outcome.date_range_used == PAST_WEEK_VALUE
    assert outcome.date_range_fallback_used is True
    assert outcome.pages_visited == 2
    assert outcome.pages_visited_past_week == 1
    assert outcome.job_selected is False  # scan_page only reports selected


@pytest.mark.asyncio
async def test_scan_on_the_week_first_choice_falls_back_to_24h(monkeypatch) -> None:
    calls: list[str] = []
    switched: list[str] = []

    async def scan_page(
        page, settings, notify, outcome, tried, applied_seen, capture, *, open_form=True
    ):
        calls.append(outcome.date_range_used)
        return _scan_result(selected=len(calls) == 2)

    async def no_next(page, settings, notify=None, reason_out=None):
        return False

    async def switch(page, settings, value, notify):
        switched.append(value)
        return True, ""

    monkeypatch.setattr(scan_mod, "go_to_next_page", no_next)
    monkeypatch.setattr(scan_mod, "switch_to_date_range", switch)

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
        preferred_range=PAST_WEEK_VALUE,
    )

    assert switched == [PAST_24_HOURS_VALUE]
    assert calls == [PAST_WEEK_VALUE, PAST_24_HOURS_VALUE]
    assert outcome.date_range_preferred == PAST_WEEK_VALUE
    assert outcome.date_range_used == PAST_24_HOURS_VALUE
    assert outcome.date_range_fallback_used is True
    assert outcome.pages_visited == 2
    assert outcome.pages_visited_past_week == 1


@pytest.mark.asyncio
async def test_scan_does_not_widen_after_a_recoverable_pagination_failure(
    monkeypatch,
) -> None:
    switched: list[str] = []

    async def scan_page(
        page, settings, notify, outcome, tried, applied_seen, capture, *, open_form=True
    ):
        return _scan_result()

    async def broken_next(page, settings, notify=None, reason_out=None):
        if reason_out is not None:
            reason_out.append("the results list did not change after the click")
        return False

    async def switch(page, settings, value, notify):  # pragma: no cover - must not run
        switched.append(value)
        return True, ""

    monkeypatch.setattr(scan_mod, "go_to_next_page", broken_next)
    monkeypatch.setattr(scan_mod, "switch_to_date_range", switch)

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
        preferred_range=PAST_24_HOURS_VALUE,
    )

    assert switched == []
    assert outcome.date_range_fallback_used is False
    assert "did not change" in outcome.notes


@pytest.mark.asyncio
async def test_scan_on_the_fallback_range_does_not_bounce_back(monkeypatch) -> None:
    calls: list[str] = []

    async def scan_page(
        page, settings, notify, outcome, tried, applied_seen, capture, *, open_form=True
    ):
        calls.append(outcome.date_range_used)
        return _scan_result(selected=True)

    async def switch(page, settings, value, notify):  # pragma: no cover - must not run
        raise AssertionError("a fallback-range pass must not switch again")

    monkeypatch.setattr(scan_mod, "switch_to_date_range", switch)

    outcome = Task2Outcome()
    # A week-first run that already fell back to 24 hours keeps scanning 24 hours.
    await scan_mod.scan_results_pages(
        object(),
        _settings(),
        lambda _m: None,
        outcome,
        set(),
        set(),
        scan_page,
        date_range=PAST_24_HOURS_VALUE,
        preferred_range=PAST_WEEK_VALUE,
    )

    assert calls == [PAST_24_HOURS_VALUE]
    assert outcome.date_range_used == PAST_24_HOURS_VALUE
    assert outcome.date_range_fallback_used is False


@pytest.mark.asyncio
async def test_scan_page_cap_does_not_start_a_new_range(monkeypatch) -> None:
    switched: list[str] = []

    async def scan_page(
        page, settings, notify, outcome, tried, applied_seen, capture, *, open_form=True
    ):
        return _scan_result()

    async def switch(page, settings, value, notify):  # pragma: no cover - must not run
        switched.append(value)
        return True, ""

    monkeypatch.setattr(scan_mod, "_MAX_RESULT_PAGES", 1)
    monkeypatch.setattr(scan_mod, "switch_to_date_range", switch)

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
        preferred_range=PAST_24_HOURS_VALUE,
    )

    assert switched == []
    assert outcome.date_range_fallback_used is False
    assert "results-page cap" in outcome.notes


@pytest.mark.asyncio
async def test_switch_to_date_range_selects_either_direction(monkeypatch) -> None:
    selected: list[str] = []
    easy_apply = [True]

    async def fake_select(page, settings, value, *, reset_start=True):
        selected.append(value)
        assert reset_start is True
        return True, ""

    async def fake_easy_apply(page):
        return easy_apply[0]

    async def fake_applied(page, tpr):
        return True

    monkeypatch.setattr(fallback_mod, "select_date_range_value", fake_select)
    monkeypatch.setattr(fallback_mod, "easy_apply_filter_selected", fake_easy_apply)
    monkeypatch.setattr(fallback_mod, "date_range_applied", fake_applied)

    ok, note = await fallback_mod.switch_to_date_range(
        object(), _settings(), PAST_WEEK_VALUE
    )
    assert ok is True
    assert note == ""
    assert selected == [PAST_WEEK_VALUE]

    ok, _note = await fallback_mod.switch_to_date_range(
        object(), _settings(), PAST_24_HOURS_VALUE
    )
    assert ok is True
    assert selected == [PAST_WEEK_VALUE, PAST_24_HOURS_VALUE]

    ok, note = await fallback_mod.switch_to_date_range(object(), _settings(), "past_month")
    assert ok is False
    assert "unsupported" in note


@pytest.mark.asyncio
async def test_switch_to_date_range_rechecks_easy_apply(monkeypatch) -> None:
    selected_easy_apply: list[bool] = []

    async def fake_select(page, settings, value, *, reset_start=True):
        return True, ""

    async def fake_easy_apply(page):
        return False

    async def fake_select_easy(page, settings, prefer_url=False):
        selected_easy_apply.append(prefer_url)
        return True, ""

    async def fake_applied(page, tpr):
        return True

    monkeypatch.setattr(fallback_mod, "select_date_range_value", fake_select)
    monkeypatch.setattr(fallback_mod, "easy_apply_filter_selected", fake_easy_apply)
    monkeypatch.setattr(fallback_mod, "select_easy_apply_filter", fake_select_easy)
    monkeypatch.setattr(fallback_mod, "date_range_applied", fake_applied)

    ok, note = await fallback_mod.switch_to_date_range(
        object(), _settings(), PAST_24_HOURS_VALUE
    )

    assert ok is True
    assert note == ""
    assert selected_easy_apply == [True]


def test_no_job_reason_explains_both_ranges() -> None:
    assert "past 24 hours or the past week" in _no_job_reason(
        Task2Outcome(
            date_range_fallback_used=True,
            date_range_preferred=PAST_24_HOURS_VALUE,
        )
    )
    assert "past week or the past 24 hours" in _no_job_reason(
        Task2Outcome(
            date_range_fallback_used=True,
            date_range_preferred=PAST_WEEK_VALUE,
        )
    )
    assert "past week" in _no_job_reason(Task2Outcome(date_range_used=PAST_WEEK_VALUE))
