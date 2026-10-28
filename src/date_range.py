"""Pure date-posted range helpers shared by the CLI, state, and browser tools.

Task 17 lets the user pick which results range the agent scans first:

* **Past 24 hours** → fall back to **Past week** when that range is exhausted;
* **Past week** → fall back to **Past 24 hours** when that range is exhausted.

This module owns the normalized range names, their LinkedIn ``f_TPR`` values,
and the choice aliases used by the startup prompt. It intentionally imports
nothing from :mod:`src.tools` so :mod:`src.state` can use it without pulling in
the browser layer.
"""

from __future__ import annotations

import re

PAST_24_HOURS_LABEL = "Past 24 hours"
PAST_24_HOURS_VALUE = "past_24_hours"
PAST_24_HOURS_TPR = "r86400"
PAST_WEEK_LABEL = "Past week"
PAST_WEEK_VALUE = "past_week"
PAST_WEEK_TPR = "r604800"
PAST_MONTH_LABEL = "Past month"
PAST_MONTH_VALUE = "past_month"
PAST_MONTH_TPR = "r2592000"

DEFAULT_DATE_RANGE = PAST_24_HOURS_VALUE
SUPPORTED_DATE_RANGES = (PAST_24_HOURS_VALUE, PAST_WEEK_VALUE)

_RANGE_LABELS = {
    PAST_24_HOURS_VALUE: PAST_24_HOURS_LABEL,
    PAST_WEEK_VALUE: PAST_WEEK_LABEL,
}
_RANGE_TPRS = {
    PAST_24_HOURS_VALUE: PAST_24_HOURS_TPR,
    PAST_WEEK_VALUE: PAST_WEEK_TPR,
}

# Accepted at the CLI prompt (and in --date-range) in addition to the
# normalized values themselves. Normalization lowercases, collapses spaces,
# and turns underscores/hyphens into spaces, so "past_24_hours", "Past 24
# Hours", and "24h" all resolve to the same range.
_ALIASES = {
    "past 24 hours": PAST_24_HOURS_VALUE,
    "24 hours": PAST_24_HOURS_VALUE,
    "24h": PAST_24_HOURS_VALUE,
    "24": PAST_24_HOURS_VALUE,
    "1": PAST_24_HOURS_VALUE,
    "past week": PAST_WEEK_VALUE,
    "past 7 days": PAST_WEEK_VALUE,
    "7 days": PAST_WEEK_VALUE,
    "7d": PAST_WEEK_VALUE,
    "week": PAST_WEEK_VALUE,
    "7": PAST_WEEK_VALUE,
    "2": PAST_WEEK_VALUE,
}


def normalize_date_range(value: str | None) -> str:
    """Return the normalized range name (``past_24_hours``/``past_week``).

    Returns ``""`` when the value is not a supported range. Only the two Task 17
    ranges are supported; **Past month** is deliberately rejected.
    """
    text = (value or "").strip().lower()
    text = re.sub(r"[\s_-]+", " ", text).strip()
    return _ALIASES.get(text, "")


def date_range_label(value: str | None) -> str:
    """The visible label for a normalized range value; ``""`` when unknown."""
    return _RANGE_LABELS.get(normalize_date_range(value), "")


def date_range_tpr_for(value: str | None) -> str:
    """The LinkedIn ``f_TPR`` value for a normalized range value; ``""`` unknown."""
    return _RANGE_TPRS.get(normalize_date_range(value), "")


def date_range_option(value: str | None) -> tuple[str, str]:
    """Return ``(label, f_TPR)`` for a normalized range value.

    Both entries are empty when the value is not a supported range, so callers
    can fail with one clear message instead of selecting the wrong filter.
    """
    normalized = normalize_date_range(value)
    if not normalized:
        return "", ""
    return _RANGE_LABELS[normalized], _RANGE_TPRS[normalized]


def other_date_range(value: str | None) -> str:
    """The range used when ``value`` is exhausted (24 hours ⇄ past week)."""
    normalized = normalize_date_range(value)
    if normalized == PAST_24_HOURS_VALUE:
        return PAST_WEEK_VALUE
    if normalized == PAST_WEEK_VALUE:
        return PAST_24_HOURS_VALUE
    return ""


__all__ = [
    "DEFAULT_DATE_RANGE",
    "PAST_24_HOURS_LABEL",
    "PAST_24_HOURS_TPR",
    "PAST_24_HOURS_VALUE",
    "PAST_MONTH_LABEL",
    "PAST_MONTH_TPR",
    "PAST_MONTH_VALUE",
    "PAST_WEEK_LABEL",
    "PAST_WEEK_TPR",
    "PAST_WEEK_VALUE",
    "SUPPORTED_DATE_RANGES",
    "date_range_label",
    "date_range_option",
    "date_range_tpr_for",
    "normalize_date_range",
    "other_date_range",
]
