"""Task 13/17: URL helpers for LinkedIn's **Date posted** range filter.

``f_TPR`` is the authoritative signal that a range is applied to the results
list. These helpers add/replace it without dropping the other filters
(``keywords``, ``f_AL=true``, …), and can reset the server-side page offset when
switching ranges (Task 17).
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.tools.linkedin_date_posted.labels import (
    PAST_24_HOURS_TPR,
    PAST_MONTH_TPR,
    PAST_WEEK_TPR,
)

_VALID_TPR = {PAST_24_HOURS_TPR, PAST_WEEK_TPR, PAST_MONTH_TPR}


def _query_pairs(url: str) -> tuple[object | None, list[tuple[str, str]]]:
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return None, []
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None, []
    return parts, parse_qsl(parts.query, keep_blank_values=True)


def url_has_date_range(url: str, tpr: str) -> bool:
    """True when the URL carries LinkedIn's ``f_TPR=<tpr>`` range."""
    wanted = (tpr or "").strip().lower()
    if not wanted:
        return False
    _parts, query = _query_pairs(url)
    return any(
        key.lower() == "f_tpr" and value.strip().lower() == wanted
        for key, value in query
    )


def with_date_range(url: str, tpr: str, *, reset_start: bool = False) -> str:
    """Return ``url`` with ``f_TPR=<tpr>``, preserving every other parameter.

    ``reset_start`` drops the results-list ``start`` offset so a range switch
    begins at page 1 (Task 17). Returns ``""`` for a URL that cannot be parsed or
    a range value that is not a known LinkedIn ``f_TPR``, so the caller stops
    instead of navigating somewhere unexpected.
    """
    wanted = (tpr or "").strip()
    if wanted.lower() not in _VALID_TPR:
        return ""
    parts, query = _query_pairs(url)
    if parts is None:
        return ""
    query = [
        (key, value)
        for key, value in query
        if key.lower() != "f_tpr" and not (reset_start and key.lower() == "start")
    ]
    query.append(("f_TPR", wanted))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def url_has_past_24_hours(url: str) -> bool:
    """True when the URL carries LinkedIn's ``f_TPR=r86400`` range."""
    return url_has_date_range(url, PAST_24_HOURS_TPR)


def with_past_24_hours(url: str) -> str:
    """Return ``url`` with ``f_TPR=r86400``, preserving every other parameter."""
    return with_date_range(url, PAST_24_HOURS_TPR)


def url_has_past_week(url: str) -> bool:
    """True when the URL carries LinkedIn's ``f_TPR=r604800`` range."""
    return url_has_date_range(url, PAST_WEEK_TPR)


def has_page_offset(url: str) -> bool:
    """True when the results URL carries a non-zero ``start`` page offset."""
    _parts, query = _query_pairs(url)
    for key, value in query:
        if key.lower() != "start":
            continue
        try:
            return int(value) > 0
        except (TypeError, ValueError):
            return False
    return False


def with_past_week(url: str, *, reset_start: bool = False) -> str:
    """Return ``url`` with ``f_TPR=r604800``, preserving every other parameter."""
    return with_date_range(url, PAST_WEEK_TPR, reset_start=reset_start)


__all__ = [
    "has_page_offset",
    "url_has_date_range",
    "url_has_past_24_hours",
    "url_has_past_week",
    "with_date_range",
    "with_past_24_hours",
    "with_past_week",
]
