"""Pure LinkedIn URL/text helpers (no browser, no network)."""

from __future__ import annotations

import re
from urllib.parse import quote_plus, urlparse

_LINKEDIN_HOST_RE = re.compile(r"(?:^|\.)linkedin\.com$", re.IGNORECASE)

# LinkedIn redirects authenticated users away from these paths.
_LOGIN_PATH_MARKERS = (
    "/login",
    "/uas/login",
    "/checkpoint",
    "/authwall",
    "/signup",
    "/register",
    "/uas/consumer-email-challenge",
)

# Paths that only render for an authenticated session.
_LOGGED_IN_PATH_MARKERS = (
    "/feed",
    "/jobs",
    "/mynetwork",
    "/messaging",
    "/notifications",
    "/in/",
    "/search",
    "/dashboard",
    "/learning",
    "/premium",
    "/my-items",
    "/company",
    "/school",
    "/groups",
)


def is_linkedin_url(url: str) -> bool:
    """True when ``url`` is an ``http(s)`` URL on a ``linkedin.com`` host."""
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    return bool(_LINKEDIN_HOST_RE.search(parsed.netloc))


def build_jobs_search_url(query: str) -> str:
    """Return the LinkedIn jobs-search URL for ``query``.

    This is the same endpoint the jobs search tab submits to.
    """
    return f"https://www.linkedin.com/jobs/search/?keywords={quote_plus((query or '').strip())}"


def is_login_path(path: str) -> bool:
    """True when ``path`` is one of LinkedIn's logged-out/auth pages."""
    normalized = (path or "").lower()
    return any(normalized.startswith(marker) for marker in _LOGIN_PATH_MARKERS)


def is_logged_in_path(path: str) -> bool:
    """True when ``path`` is a page that requires an authenticated session."""
    normalized = (path or "").lower()
    if is_login_path(normalized):
        return False
    return any(normalized.startswith(marker) for marker in _LOGGED_IN_PATH_MARKERS)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def looks_like_easy_apply(text: str) -> bool:
    """True when ``text`` advertises LinkedIn's built-in Easy Apply.

    The exact phrase is used so that an external "Apply" button (which sends the
    user to a company website) is *not* mistaken for Easy Apply.
    """
    return "easy apply" in _normalize(text)


def looks_like_easy_apply_filter(text: str) -> bool:
    """True when ``text`` labels the results-page Easy Apply *filter* toggle.

    The filter's accessible name is e.g. "Easy Apply filter.", which also matches
    :func:`looks_like_easy_apply`; requiring "filter" tells it apart from a job's
    Easy Apply *button* ("Easy Apply to <job> at <company>").
    """
    normalized = _normalize(text)
    return "easy apply" in normalized and "filter" in normalized


def looks_like_easy_apply_action(text: str) -> bool:
    """True when ``text`` labels a job's Easy Apply *button* in the details pane."""
    normalized = _normalize(text)
    return "easy apply" in normalized and "filter" not in normalized


def _pick_index(labels: list[str], predicate) -> int | None:
    for index, label in enumerate(labels):
        if predicate(label):
            return index
    return None


def pick_easy_apply_index(labels: list[str]) -> int | None:
    """Return the index of the first label that looks like Easy Apply, if any."""
    return _pick_index(labels, looks_like_easy_apply)


def pick_easy_apply_filter_index(labels: list[str]) -> int | None:
    """Return the index of the first Easy Apply *filter* label, if any."""
    return _pick_index(labels, looks_like_easy_apply_filter)


def pick_easy_apply_action_index(labels: list[str]) -> int | None:
    """Return the index of the first Easy Apply *button* label, if any."""
    return _pick_index(labels, looks_like_easy_apply_action)


# Phrases that appear in LinkedIn's Easy Apply application form/modal.
_APPLY_MODAL_HINTS = (
    "easy apply",
    "apply to",
    "submit application",
    "review your application",
)


def looks_like_apply_modal(text: str) -> bool:
    """True when ``text`` looks like the Easy Apply application form/modal."""
    normalized = _normalize(text)
    return any(hint in normalized for hint in _APPLY_MODAL_HINTS)


# aria-label / placeholder text on the jobs search bar's keywords input.
_JOBS_SEARCH_INPUT_HINTS = (
    "title, skill, or company",
    "search by title",
    "search jobs",
    "search for jobs",
)


def looks_like_jobs_search_input(text: str) -> bool:
    """True when ``text`` (an aria-label/placeholder) labels the jobs search bar."""
    normalized = _normalize(text)
    return any(hint in normalized for hint in _JOBS_SEARCH_INPUT_HINTS)
