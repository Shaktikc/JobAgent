"""Task 17: widen LinkedIn's **Date posted** filter from Past 24 hours to Past week.

When the 24-hour results list has no unapplied Easy Apply job left, the agent
must keep looking at older postings. This module owns that transition:

* detect which range the current results list uses (the ``f_TPR`` URL parameter
  is authoritative; a checked Date posted option is the fallback),
* select **Past week** through the visible filter UI, or through the URL when a
  layout hides the dropdown,
* reset the results pagination to page 1,
* re-check/re-apply the **Easy Apply** filter because the range reload can reset
  it, and verify both filters together.

It never switches to **Past month** and never opens or submits a job; the
results-page walk in :mod:`src.tools.linkedin_results_scan` owns the scanning.
"""

from __future__ import annotations

from src.configuration import Settings
from src.tools.linkedin_date_posted import (
    PAST_24_HOURS_TPR,
    PAST_24_HOURS_VALUE,
    PAST_WEEK_TPR,
    PAST_WEEK_VALUE,
    date_range_applied,
    looks_like_past_24_hours,
    looks_like_past_week,
    read_date_controls,
    select_past_week,
)
from src.tools.linkedin_search.easy_apply_filter import (
    easy_apply_filter_selected,
    select_easy_apply_filter,
)
from src.tools.linkedin_status_overlay import emit_step


def _join_notes(*notes: str) -> str:
    return "; ".join(note for note in notes if note)


async def current_date_range(page) -> str:
    """The results list's current date range (``past_24_hours``/``past_week``).

    ``f_TPR`` in the URL is authoritative. When the URL is not available (for
    example after a click navigated to a job view), a checked **Past week** or
    **Past 24 hours** control is trusted. Returns ``""`` when neither signal is
    present, so the caller keeps its legacy single-range behaviour instead of
    guessing.
    """
    if await date_range_applied(page, PAST_WEEK_TPR):
        return PAST_WEEK_VALUE
    if await date_range_applied(page, PAST_24_HOURS_TPR):
        return PAST_24_HOURS_VALUE
    for control in await read_date_controls(page):
        if not control.get("checked"):
            continue
        label = control.get("label", "")
        if looks_like_past_week(label):
            return PAST_WEEK_VALUE
        if looks_like_past_24_hours(label):
            return PAST_24_HOURS_VALUE
    return ""


async def switch_to_past_week(
    page,
    settings: Settings,
    notify=None,
) -> tuple[bool, str]:
    """Select **Date posted → Past week**, reset page 1, and keep Easy Apply.

    Returns ``(selected, note)``. The range is verified through
    ``f_TPR=r604800``, not merely a checked radio. If the range reload resets
    the Easy Apply pill, it is re-applied through ``f_AL=true`` so the date range
    is preserved. Both filters must be active together before scanning resumes.
    """
    notify = notify or (lambda _message: None)
    notify("Task 17: no more Past 24 hours jobs to scan; switching to Past week.")
    emit_step(
        notify,
        "Please wait - no more jobs posted in the past 24 hours; "
        "widening the search to the past week...",
    )

    selected, note = await select_past_week(page, settings)
    if not selected:
        return False, note or "the Past week filter could not be selected"

    if not await easy_apply_filter_selected(page):
        applied, easy_note = await select_easy_apply_filter(
            page, settings, prefer_url=True
        )
        note = _join_notes(note, easy_note)
        if not applied:
            return False, note or "Easy Apply could not be re-selected for Past week"

    # Re-applying Easy Apply navigates; a slow reload can drop the range. Verify
    # both filters together, retrying the range once through the generic helper
    # (which preserves f_AL and resets the page offset).
    if not await date_range_applied(page, PAST_WEEK_TPR):
        reselected, range_note = await select_past_week(page, settings)
        note = _join_notes(note, range_note)
        if not reselected:
            return False, note or "the Past week filter was lost after re-applying Easy Apply"
        if not await easy_apply_filter_selected(page):
            applied, easy_note = await select_easy_apply_filter(
                page, settings, prefer_url=True
            )
            note = _join_notes(note, easy_note)
            if not applied:
                return False, note or "Easy Apply was lost after selecting Past week"

    if not await date_range_applied(page, PAST_WEEK_TPR):
        return False, note or "the Past week filter could not be verified"

    emit_step(notify, "Scanning jobs posted in the past week...")
    return True, note


__all__ = ["current_date_range", "switch_to_past_week"]
