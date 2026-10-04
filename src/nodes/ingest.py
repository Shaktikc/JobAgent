"""Validate and normalize the run input (Task 1 inputs)."""

from __future__ import annotations

from src.state import ApplyState
from src.tools.linkedin import is_linkedin_url


def ingest(state: ApplyState) -> ApplyState:
    """Check the login URL and the search query before touching the browser."""
    url = (state.get("url") or "").strip()
    query = (state.get("search_query") or "").strip()

    if not url:
        return {"status": "failed", "errors": ["ingest: no login URL provided"]}
    if not is_linkedin_url(url):
        return {"status": "failed", "errors": [f"ingest: not a LinkedIn URL: {url}"]}
    if not query:
        return {"status": "failed", "errors": ["ingest: no search query provided"]}

    return {
        "search_query": query,
        "status": "logging_in",
        "log": [f"ingest: url={url} search_query={query!r}"],
    }
