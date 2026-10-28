"""Task 13/17: pure label and range helpers for LinkedIn's **Date posted** filter.

These helpers carry no browser state: they normalize labels and map the three
range options to LinkedIn's ``f_TPR`` values and the agent's normalized range
names. Task 13 uses the **Past 24 hours** entries; Task 17 adds **Past week** for
the post-24-hour fallback.
"""

from __future__ import annotations

import re

# LinkedIn's f_TPR values and the agent's normalized range names. Only
# ``r86400``/``past_24_hours`` satisfies Task 13; Task 17 widens to
# ``r604800``/``past_week``; ``past_month`` is intentionally never selected.
_RANGE_SPECS = {
    "past 24 hours": (86400, "r86400", "past_24_hours"),
    "past week": (604800, "r604800", "past_week"),
    "past month": (2592000, "r2592000", "past_month"),
}
PAST_24_HOURS_LABEL = "Past 24 hours"
PAST_24_HOURS_VALUE = "past_24_hours"
PAST_24_HOURS_TPR = "r86400"
PAST_WEEK_LABEL = "Past week"
PAST_WEEK_VALUE = "past_week"
PAST_WEEK_TPR = "r604800"
PAST_MONTH_LABEL = "Past month"
PAST_MONTH_VALUE = "past_month"
PAST_MONTH_TPR = "r2592000"


def normalize_label(text: str) -> str:
    """Collapse whitespace, lowercase, and drop a trailing period."""
    return re.sub(r"\s+", " ", (text or "").strip().lower()).rstrip(".")


def _range_key(text: str) -> str:
    """Normalized range/filter label without a trailing "filter" suffix."""
    return re.sub(r"\s+filter$", "", normalize_label(text))


def looks_like_date_range(text: str) -> bool:
    """True for the popover's range labels (Past 24 hours/week/month)."""
    return _range_key(text) in _RANGE_SPECS


def looks_like_past_24_hours(text: str) -> bool:
    """True when ``text`` is the **Past 24 hours** option."""
    return _range_key(text) == PAST_24_HOURS_LABEL.lower()


def looks_like_past_week(text: str) -> bool:
    """True when ``text`` is the **Past week** option."""
    return _range_key(text) == PAST_WEEK_LABEL.lower()


def date_range_seconds(text: str) -> int | None:
    """The range's duration in seconds; ``None`` when the label is not a range."""
    spec = _RANGE_SPECS.get(_range_key(text))
    return spec[0] if spec else None


def date_range_tpr(text: str) -> str:
    """The LinkedIn ``f_TPR`` value for a range label; ``""`` when unknown."""
    spec = _RANGE_SPECS.get(_range_key(text))
    return spec[1] if spec else ""


def date_range_value(text: str) -> str:
    """The normalized range name (``past_24_hours``, …); ``""`` when unknown."""
    spec = _RANGE_SPECS.get(_range_key(text))
    return spec[2] if spec else ""


def looks_like_date_posted_filter(text: str) -> bool:
    """True when ``text`` labels the results-page **Date posted** filter.

    Accepts the generic pill label ("Date posted" / "Date posted filter.") and
    the selected-range label LinkedIn may show instead ("Past 24 hours", "Past
    week", "Past month"). It deliberately requires the phrase **date posted** (or
    an exact range label), so a job card's "Posted 1 day ago" is never matched.
    """
    normalized = _range_key(text)
    return normalized == "date posted" or normalized in _RANGE_SPECS


def pick_date_range_index(labels: list[str], label: str) -> int | None:
    """Return the index of the exact range ``label``, if any."""
    wanted = normalize_label(label)
    for index, candidate in enumerate(labels):
        if normalize_label(candidate) == wanted:
            return index
    return None


def pick_past_24_hours_index(labels: list[str]) -> int | None:
    """Return the index of the **Past 24 hours** label, if any."""
    return pick_date_range_index(labels, PAST_24_HOURS_LABEL)


def pick_past_week_index(labels: list[str]) -> int | None:
    """Return the index of the **Past week** label, if any."""
    return pick_date_range_index(labels, PAST_WEEK_LABEL)


def pick_date_posted_filter_index(labels: list[str]) -> int | None:
    """Return the index of the **Date posted** filter label, if any."""
    for index, label in enumerate(labels):
        if looks_like_date_posted_filter(label):
            return index
    return None


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
    "date_range_seconds",
    "date_range_tpr",
    "date_range_value",
    "looks_like_date_posted_filter",
    "looks_like_date_range",
    "looks_like_past_24_hours",
    "looks_like_past_week",
    "normalize_label",
    "pick_date_posted_filter_index",
    "pick_date_range_index",
    "pick_past_24_hours_index",
    "pick_past_week_index",
]
