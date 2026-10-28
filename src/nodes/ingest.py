"""Validate and normalize the run input (Task 1 inputs)."""

from __future__ import annotations

from src.date_range import DEFAULT_DATE_RANGE, normalize_date_range
from src.state import ApplyState
from src.tools.linkedin import is_linkedin_url


def ingest(state: ApplyState) -> ApplyState:
    """Check the login URL, search query, and startup date range."""
    url = (state.get("url") or "").strip()
    query = (state.get("search_query") or "").strip()
    requested_range = (state.get("date_range") or "").strip() or DEFAULT_DATE_RANGE
    date_range = normalize_date_range(requested_range)

    if not url:
        return {"status": "failed", "errors": ["ingest: no login URL provided"]}
    if not is_linkedin_url(url):
        return {"status": "failed", "errors": [f"ingest: not a LinkedIn URL: {url}"]}
    if not query:
        return {"status": "failed", "errors": ["ingest: no search query provided"]}
    if not date_range:
        return {
            "status": "failed",
            "errors": [
                f"ingest: unknown date range {requested_range!r}; "
                "choose past_24_hours or past_week"
            ],
        }

    return {
        "search_query": query,
        "date_range": date_range,
        "status": "logging_in",
        "log": [
            f"ingest: url={url} search_query={query!r} date_range={date_range}"
        ],
    }
