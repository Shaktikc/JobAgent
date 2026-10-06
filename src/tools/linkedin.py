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


# Job-card labels carry location/status metadata that a job's apply button label
# ("Easy Apply to <job> at <company>") does not. These are the same markers the
# AI/semantic job-card scanner (:data:`_AI_JOB_CARDS_JS`) uses, so a card's
# "Easy Apply" badge is never mistaken for the details pane's apply button.
_JOB_CARD_MARKERS = (
    "on-site",
    "hybrid",
    "remote",
    "posted",
    "actively reviewing",
    "applied",
    "promoted",
)


def looks_like_job_card_label(text: str) -> bool:
    """True when ``text`` reads like a job card, not a job's apply button.

    A job card's accessible text carries the title plus location/status metadata
    ("On-site", "Hybrid", "Remote", "Actively reviewing applicants", "Posted",
    "Applied"). The details pane's apply button is short ("Easy Apply to <job> at
    <company>") and rarely contains those markers, so requiring one keeps a job
    card's "Easy Apply" badge from being chosen as the apply button.
    """
    normalized = _normalize(text)
    return any(marker in normalized for marker in _JOB_CARD_MARKERS)


def card_is_applied(text: str) -> bool:
    """True when a job card's status marks the job as already applied.

    A card that the user has already applied to shows the word **Applied** in its
    status line (e.g. "Applied · 5 months ago"). Only that standalone word
    decides: the age text ("5 months ago", "2 weeks ago") and other statuses
    ("Viewed", "Saved") are ignored, as is an "Easy Apply" badge. Matching is on
    the normalized card text (trim, lowercase, collapse whitespace) because the
    status label's markup and position vary, and an unreadable/empty card is
    never assumed Applied — the caller lets the existing Easy Apply check decide.
    """
    return bool(re.search(r"\bapplied\b", _normalize(text)))


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


# LinkedIn's AI-powered job search entry point. It is offered as an optional
# button/link (e.g. "Try AI job search"); the exact wording varies, so match an
# "AI" token (or the spelled-out phrase) together with the word "search".
_AI_TOKEN_RE = re.compile(r"(?<![a-z])ai(?![a-z])")


def looks_like_ai_job_search(text: str) -> bool:
    """True when ``text`` labels LinkedIn's "Try AI job search" control.

    Matches any accessible label that mentions AI (as the token ``AI`` or
    ``Artificial Intelligence``) **and** searching, so variants like
    "Try AI-powered job search", "Search with AI", or "AI-powered search" are
    all recognised while unrelated controls ("Save this search",
    "AI resume builder") are not.
    """
    normalized = _normalize(text)
    mentions_ai = bool(_AI_TOKEN_RE.search(normalized)) or "artificial intelligence" in normalized
    return mentions_ai and "search" in normalized


def pick_ai_job_search_index(labels: list[str]) -> int | None:
    """Return the index of the first AI job search label, if any."""
    return _pick_index(labels, looks_like_ai_job_search)


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
    # LinkedIn's AI job search page uses a "describe what you want" prompt.
    "describe the job",
    "describe the job you want",
)


def looks_like_jobs_search_input(text: str) -> bool:
    """True when ``text`` (an aria-label/placeholder) labels the jobs search bar."""
    normalized = _normalize(text)
    return any(hint in normalized for hint in _JOBS_SEARCH_INPUT_HINTS)
