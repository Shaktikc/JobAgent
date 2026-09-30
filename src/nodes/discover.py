"""`discovery` — read a job posting via the browser-use agent.

Rewritten in Task 17 (ADR 0001): the read is the agent's structured output against
``linkedin.JobExtraction``. The node still emits the same :class:`~src.state.JobState`
contract, and still refuses a non-Easy-Apply job *before* anything can fill it.

All browser/network work routes through ``src/tools/browser_agent.run_task`` (which
brackets ``guard``); this node stays thin.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.state import JobState
from src.tools import browser as browser_tools
from src.tools import linkedin
from src.tools.browser_agent import run_task

if TYPE_CHECKING:  # type-only: the guard is optional and passed in by the caller
    from src.tools.guard import Guard

logger = logging.getLogger(__name__)

READ_ONLY_SYSTEM_MESSAGE = (
    "You may only read pages. Never click Apply, Easy Apply, or anything that "
    "submits or fills an application. Do not log in or change any settings."
)


class NotEasyApplyError(RuntimeError):
    """Raised when a job does not offer Easy Apply and must not be queued."""


class DiscoveryError(RuntimeError):
    """The agent did not return a usable job extraction."""


def ensure_easy_apply(extraction: linkedin.JobExtraction, *, label: str) -> None:
    """Refuse a job that has no Easy Apply, before any filling is attempted."""
    if not extraction.easy_apply:
        raise NotEasyApplyError(
            f"Job {label!r} does not offer LinkedIn Easy Apply; not queuing it."
        )


def as_job_state(extraction: linkedin.JobExtraction, *, url: str) -> JobState:
    """Project the agent's read onto the shared :class:`~src.state.JobState` contract."""
    return JobState(
        job_id=linkedin.job_id_from_url(url),
        title=extraction.title,
        company=extraction.company,
        url=url,
        description=extraction.description,
        easy_apply=extraction.easy_apply,
    )


async def read_job(
    browser: Any,
    llm: Any,
    url: str,
    *,
    guard: Guard | None = None,
) -> JobState:
    """Read one job URL with the browser-use agent and emit its ``JobState``.

    Easy Apply is checked here, before returning — so no caller can start filling a
    job that is not Easy Apply.
    """
    result = await run_task(
        linkedin.build_read_job_task(url),
        llm=llm,
        browser=browser,
        system_message=READ_ONLY_SYSTEM_MESSAGE,
        output_model_schema=linkedin.JobExtraction,
        guard=guard,
    )
    extraction = result.structured_output
    if not isinstance(extraction, linkedin.JobExtraction):
        raise DiscoveryError("the browser-use agent did not return a job extraction")

    if guard is not None:
        guard.check_page_text(await browser_tools.read_page_text(browser))

    ensure_easy_apply(extraction, label=url)
    logger.info(
        "discovery: read job job_id=%s title=%r company=%r",
        linkedin.job_id_from_url(url),
        extraction.title,
        extraction.company,
    )
    return as_job_state(extraction, url=url)
