"""Task 17: fall back between LinkedIn's **Past 24 hours** and **Past week**.

The user chooses the primary range at startup. When every job in that range has
been scanned and no openable job is left, the agent switches to the other range:

* Past 24 hours → Past week
* Past week → Past 24 hours

This module owns that transition:

* detect which range the current results list uses (the ``f_TPR`` URL parameter
  is authoritative; a checked Date posted option is the fallback),
* select the target range through the visible filter UI, or through the URL
  when a layout hides the dropdown,
* reset the results pagination to page 1,
* re-check/re-apply the **Easy Apply** filter because the range reload can reset
  it, and verify both filters together.

It never switches to **Past month** and never opens or submits a job; the
results-page walk in :mod:`src.tools.linkedin_results_scan` owns the scanning.
"""

from __future__ import annotations

from src.configuration import Settings
from src.date_range import date_range_label, date_range_option, other_date_range
from src.tools.linkedin_date_posted import (
    PAST_24_HOURS_TPR,
    PAST_24_HOURS_VALUE,
    PAST_WEEK_TPR,
    PAST_WEEK_VALUE,
    date_range_applied,
    looks_like_past_24_hours,
    looks_like_past_week,
    read_date_controls,
    select_date_range_value,
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


async def switch_to_date_range(
    page,
    settings: Settings,
    value: str,
    notify=None,
) -> tuple[bool, str]:
    """Select **Date posted → ``value``**, reset page 1, and keep Easy Apply.

    ``value`` is ``past_24_hours`` or ``past_week``. Returns ``(selected, note)``.
    The range is verified through ``f_TPR``, not merely a checked radio. If the
    range reload resets the Easy Apply pill, it is re-applied through
    ``f_AL=true`` so the date range is preserved. Both filters must be active
    together before scanning resumes.
    """
    notify = notify or (lambda _message: None)
    target_label, target_tpr = date_range_option(value)
    if not target_label:
        return False, f"unsupported date range {value!r}"

    source_value = other_date_range(value)
    source_label = date_range_label(source_value) or "the current range"
    notify(
        f"Task 17: no more {source_label} jobs to scan; "
        f"switching to {target_label}."
    )
    emit_step(
        notify,
        f"Please wait - no more jobs posted in the {source_label.lower()}; "
        f"falling back to the {target_label.lower()}...",
    )

    selected, note = await select_date_range_value(page, settings, value, reset_start=True)
    if not selected:
        return False, note or f"the {target_label} filter could not be selected"

    if not await easy_apply_filter_selected(page):
        applied, easy_note = await select_easy_apply_filter(
            page, settings, prefer_url=True
        )
        note = _join_notes(note, easy_note)
        if not applied:
            return False, note or f"Easy Apply could not be re-selected for {target_label}"

    # Re-applying Easy Apply navigates; a slow reload can drop the range. Verify
    # both filters together, retrying the range once through the generic helper
    # (which preserves f_AL and resets the page offset).
    if not await date_range_applied(page, target_tpr):
        reselected, range_note = await select_date_range_value(
            page, settings, value, reset_start=True
        )
        note = _join_notes(note, range_note)
        if not reselected:
            return False, note or f"the {target_label} filter was lost after re-applying Easy Apply"
        if not await easy_apply_filter_selected(page):
            applied, easy_note = await select_easy_apply_filter(
                page, settings, prefer_url=True
            )
            note = _join_notes(note, easy_note)
            if not applied:
                return False, note or f"Easy Apply was lost after selecting {target_label}"

    if not await date_range_applied(page, target_tpr):
        return False, note or f"the {target_label} filter could not be verified"

    emit_step(notify, f"Scanning jobs posted in the {target_label.lower()}...")
    return True, note


async def switch_to_past_week(
    page,
    settings: Settings,
    notify=None,
) -> tuple[bool, str]:
    """Compatibility wrapper for the original 24-hours → week fallback."""
    return await switch_to_date_range(page, settings, PAST_WEEK_VALUE, notify)


__all__ = ["current_date_range", "switch_to_date_range", "switch_to_past_week"]
