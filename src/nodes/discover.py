"""`discovery` — search LinkedIn, harvest job cards, filter, extract details.

Implemented in two parts:
- Task 5: read a single job URL and detect Easy Apply availability.
- Task 12: run the search from ``config/search.yaml``, apply filters, dedupe.

All network access goes through ``src/tools/linkedin.py`` and ``src/tools/guard.py``;
this node stays testable against saved HTML fixtures.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from playwright.sync_api import Page

from src.state import JobState
from src.tools import linkedin

if TYPE_CHECKING:  # type-only: the guard is optional and passed in by the caller
    from src.tools.guard import Guard

logger = logging.getLogger(__name__)


class NotEasyApplyError(RuntimeError):
    """Raised when a job does not offer Easy Apply and must not be queued.

    Typed so callers can skip the job cleanly instead of proceeding to filling
    (Task 5 acceptance: a non-Easy-Apply job raises rather than proceeding).
    """


def ensure_easy_apply(details: linkedin.JobDetails) -> None:
    """Refuse a job that has no Easy Apply button, before any filling is attempted."""
    if not details.easy_apply:
        label = details.job_id or details.url
        raise NotEasyApplyError(
            f"Job {label!r} does not offer LinkedIn Easy Apply; not queuing it."
        )


def as_job_state(details: linkedin.JobDetails) -> JobState:
    """Project parsed details onto the shared :class:`~src.state.JobState` contract."""
    return JobState(
        job_id=details.job_id,
        title=details.title,
        company=details.company,
        url=details.url,
        description=details.description,
        easy_apply=details.easy_apply,
    )


def extract_job(html: str, *, url: str) -> JobState:
    """Parse a job page (pure) and emit its ``JobState``, or raise if not Easy Apply.

    No browser and no network: usable directly against saved HTML fixtures.
    """
    details = linkedin.parse_job_page(html, url=url)
    ensure_easy_apply(details)
    logger.info(
        "discovery: read job job_id=%s title=%r company=%r",
        details.job_id,
        details.title,
        details.company,
    )
    return as_job_state(details)


def read_job(page: Page, url: str, *, guard: Guard | None = None) -> JobState:
    """Fetch one job URL through the browser and emit its ``JobState``.

    Easy Apply is checked here, before returning — so no caller can start filling
    a job that is not Easy Apply.
    """
    details = linkedin.read_job(page, url, guard=guard)
    ensure_easy_apply(details)
    return as_job_state(details)
