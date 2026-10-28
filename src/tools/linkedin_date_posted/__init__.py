"""Task 13/17: LinkedIn's **Date posted** filter.

This package replaces the former single-module ``linkedin_date_posted.py``. It
keeps the public API stable via the re-exports below, so existing imports such as
``from src.tools.linkedin_date_posted import select_past_24_hours`` keep working
unchanged.

Modules by concern:

* :mod:`.labels` — pure label/range helpers and constants;
* :mod:`.urls` — ``f_TPR`` URL helpers (add/replace a range, reset the page
  offset);
* :mod:`.queries` — runtime discovery scripts for the pill/options/apply button;
* :mod:`.selection` — the deterministic browser steps and verification.
"""

from __future__ import annotations

from src.tools.linkedin_date_posted.labels import (
    PAST_24_HOURS_LABEL,
    PAST_24_HOURS_TPR,
    PAST_24_HOURS_VALUE,
    PAST_MONTH_LABEL,
    PAST_MONTH_TPR,
    PAST_MONTH_VALUE,
    PAST_WEEK_LABEL,
    PAST_WEEK_TPR,
    PAST_WEEK_VALUE,
    date_range_seconds,
    date_range_tpr,
    date_range_value,
    looks_like_date_posted_filter,
    looks_like_date_range,
    looks_like_past_24_hours,
    looks_like_past_week,
    normalize_label,
    pick_date_posted_filter_index,
    pick_date_range_index,
    pick_past_24_hours_index,
    pick_past_week_index,
)
from src.tools.linkedin_date_posted.selection import (
    _DATE_OPTION_POLL_SECONDS,
    _DATE_OPTION_TIMEOUT_SECONDS,
    date_posted_filter_applied,
    date_posted_filter_selected,
    date_range_applied,
    date_range_selected,
    find_date_posted_filter,
    find_show_results_button,
    read_date_controls,
    read_date_options,
    select_date_range,
    select_date_range_value,
    select_past_24_hours,
    select_past_week,
    wait_for_past_24_hours_option,
    wait_for_past_week_option,
    wait_for_range_option,
)
from src.tools.linkedin_date_posted.urls import (
    has_page_offset,
    url_has_date_range,
    url_has_past_24_hours,
    url_has_past_week,
    with_date_range,
    with_past_24_hours,
    with_past_week,
)

__all__ = [
    "PAST_24_HOURS_LABEL",
    "PAST_24_HOURS_TPR",
    "PAST_24_HOURS_VALUE",
    "PAST_MONTH_LABEL",
    "PAST_MONTH_TPR",
    "PAST_MONTH_VALUE",
    "PAST_WEEK_LABEL",
    "PAST_WEEK_TPR",
    "PAST_WEEK_VALUE",
    "_DATE_OPTION_POLL_SECONDS",
    "_DATE_OPTION_TIMEOUT_SECONDS",
    "date_posted_filter_applied",
    "date_posted_filter_selected",
    "date_range_applied",
    "date_range_seconds",
    "date_range_selected",
    "date_range_tpr",
    "date_range_value",
    "find_date_posted_filter",
    "find_show_results_button",
    "has_page_offset",
    "looks_like_date_posted_filter",
    "looks_like_date_range",
    "looks_like_past_24_hours",
    "looks_like_past_week",
    "normalize_label",
    "pick_date_posted_filter_index",
    "pick_date_range_index",
    "pick_past_24_hours_index",
    "pick_past_week_index",
    "read_date_controls",
    "read_date_options",
    "select_date_range",
    "select_date_range_value",
    "select_past_24_hours",
    "select_past_week",
    "url_has_date_range",
    "url_has_past_24_hours",
    "url_has_past_week",
    "wait_for_past_24_hours_option",
    "wait_for_past_week_option",
    "wait_for_range_option",
    "with_date_range",
    "with_past_24_hours",
    "with_past_week",
]
