"""Tasks 7/17: walk LinkedIn results pages across the selected date range.

Task 7 advances the results list while a page yields no openable Easy Apply job.
Task 17 adds one controlled widening: when the **Past 24 hours** range is
genuinely exhausted, the Date posted filter is switched to **Past week** (page 1)
and the same page scan continues there. The week range contains the 24-hour jobs,
so the caller's already-tried keys and applied set carry over and prevent
duplicate work. **Past month** is never selected.

This module owns only the page/range orchestration; the card scan itself is the
caller's ``scan_page`` callback (Task 2's :func:`_scan_page`), which keeps the
file-size limit and reusable unit-test seams.
"""

from __future__ import annotations

from collections.abc import Callable

from src.configuration import Settings
from src.state import Task2Outcome
from src.tools.browser import _append_note, _pace, results_count
from src.tools.linkedin_date_posted import (
    PAST_24_HOURS_VALUE,
    PAST_WEEK_LABEL,
    PAST_WEEK_VALUE,
)
from src.tools.linkedin_date_range_fallback import (
    current_date_range,
    switch_to_past_week,
)
from src.tools.linkedin_pagination import _MAX_RESULT_PAGES, go_to_next_page
from src.tools.linkedin_skip_applied import applied_skip_note
from src.tools.linkedin_status_overlay import emit_step

# A pagination failure that means the current page has not been fully scanned:
# the control gone or the list unchanged. Never start a new range after those.
_RECOVERABLE_PAGINATION_FAILURES = (
    "did not change",
    "disappeared",
)

# (normalized range name, visible label) in the order they are scanned.
_SCAN_RANGES = (
    (PAST_24_HOURS_VALUE, ""),
    (PAST_WEEK_VALUE, PAST_WEEK_LABEL),
)


def scan_ranges(date_range: str) -> tuple[tuple[str, str], ...]:
    """The ranges to scan for a detected/requested ``date_range``.

    A known **Past week** list scans only the week; a known **Past 24 hours**
    list scans 24 hours and then the week; an unknown range keeps the legacy
    single-range behaviour (no fallback guess).
    """
    if date_range == PAST_WEEK_VALUE:
        return (_SCAN_RANGES[1],)
    if date_range == PAST_24_HOURS_VALUE:
        return _SCAN_RANGES
    return (_SCAN_RANGES[0],)


async def _switch_range(
    page,
    settings: Settings,
    notify,
    outcome: Task2Outcome,
) -> bool:
    """Widen to Past week and record the failure note when it cannot be applied."""
    selected, note = await switch_to_past_week(page, settings, notify)
    if note:
        outcome.notes = _append_note(outcome.notes, note)
    if not selected:
        outcome.notes = _append_note(
            outcome.notes,
            "no job remained in the past 24 hours and the Past week filter "
            "could not be selected",
        )
    return selected


def _is_recoverable_pagination_failure(reason: str) -> bool:
    """True when pagination failed before the current page was fully scanned."""
    normalized = (reason or "").lower()
    return any(marker in normalized for marker in _RECOVERABLE_PAGINATION_FAILURES)


async def scan_results_pages(
    page,
    settings: Settings,
    notify,
    outcome: Task2Outcome,
    tried: set[str],
    applied_seen: set[str],
    scan_page: Callable,
    *,
    capture=None,
    open_form: bool = True,
    date_range: str = "",
) -> None:
    """Scan pages, widening 24 hours → week only when the range is exhausted.

    ``scan_page`` is Task 2's page scanner (same signature as ``_scan_page``);
    it opens the first selectable job or reports the page as empty. This function
    owns the page cap, pagination, and the Task 17 range switch. It never opens or
    applies to a job itself.
    """
    range_value = date_range or await current_date_range(page)
    ranges = scan_ranges(range_value)
    outcome.date_range_used = range_value or ranges[0][0]
    pages_visited = 0
    pages_visited_past_week = 0
    exhausted = False
    selected_any = False

    for range_index, (name, _label) in enumerate(ranges):
        if range_index:
            if not await _switch_range(page, settings, notify, outcome):
                break
            outcome.date_range_fallback_used = True
        outcome.date_range_used = name
        range_exhausted = False

        for page_index in range(_MAX_RESULT_PAGES):
            pages_visited += 1
            if name == PAST_WEEK_VALUE:
                pages_visited_past_week += 1
            scan = await scan_page(
                page,
                settings,
                notify,
                outcome,
                tried,
                applied_seen,
                capture,
                open_form=open_form,
            )
            outcome.jobs_seen = scan.cards_seen or await results_count(page)
            notify(f"Task 2: {outcome.jobs_seen} job(s) in the list.")
            await _pace(settings)
            if scan.opened or scan.selected:
                selected_any = True
                break
            if scan.cards_seen == 0:
                range_exhausted = True
                break
            if page_index == _MAX_RESULT_PAGES - 1:
                outcome.notes = _append_note(
                    outcome.notes,
                    f"reached the results-page cap ({_MAX_RESULT_PAGES}) "
                    "while every page was Applied",
                )
                break

            pagination_reason: list[str] = []
            if not await go_to_next_page(
                page, settings, notify, reason_out=pagination_reason
            ):
                reason = pagination_reason[0] if pagination_reason else ""
                if reason:
                    outcome.notes = _append_note(outcome.notes, reason)
                if _is_recoverable_pagination_failure(reason):
                    # The current range is not fully scanned; a range switch
                    # would skip jobs rather than find older ones.
                    break
                range_exhausted = True
                break

        if selected_any:
            break
        if not range_exhausted:
            break
        exhausted = True

    outcome.pages_visited = pages_visited
    outcome.pages_visited_past_week = pages_visited_past_week

    if not outcome.easy_apply_clicked and not outcome.job_selected:
        if outcome.date_range_fallback_used:
            outcome.notes = _append_note(
                outcome.notes,
                "no unapplied Easy Apply job was found in the past 24 hours "
                "or the past week",
            )
        else:
            note = applied_skip_note(outcome)
            if note:
                outcome.notes = _append_note(outcome.notes, note)
        if exhausted and pages_visited > 1:
            if outcome.date_range_fallback_used:
                outcome.notes = _append_note(
                    outcome.notes,
                    f"searched {pages_visited} results page(s) across the past "
                    "24 hours and past week; no openable Easy Apply job was found",
                )
            else:
                outcome.notes = _append_note(
                    outcome.notes,
                    f"searched {pages_visited} results page(s); "
                    "no openable Easy Apply job was found",
                )
    emit_step(notify, "Finished scanning the selected date range(s).")


__all__ = ["scan_ranges", "scan_results_pages"]
