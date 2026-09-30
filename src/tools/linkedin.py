"""`session` (LinkedIn operations) — URL helpers + the agent job-read task.

Rewritten in Task 17 (ADR 0001): the browser half is now a browser-use agent task
plus thin helpers over the session's current URL. The hand-written HTML parser and
direct page reads are gone; reading is the agent's structured output.

Everything here except ``wait_for_login`` is pure and unit-testable without a
browser or an LLM.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from pydantic import BaseModel

LOGIN_URL = "https://www.linkedin.com/login"
FEED_URL = "https://www.linkedin.com/feed/"
MYNETWORK_URL = "https://www.linkedin.com/mynetwork/"

# URL fragments that identify an authenticated session vs. a login wall.
LOGGED_IN_URL_MARKERS = ("/feed", "/mynetwork")
LOGGED_OUT_URL_MARKERS = ("/login", "/authwall", "/checkpoint", "/uas/")


def job_id_from_url(url: str) -> str:
    """Extract the LinkedIn numeric job id from a job/view or search URL.

    Raises ``ValueError`` for a URL that carries no job id, so a bad URL fails
    loudly instead of deduping everything under an empty key.
    """
    for pattern in (r"/jobs/view/(\d+)", r"[?&]currentJobId=(\d+)"):
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"cannot determine LinkedIn job id from URL: {url!r}")


def login_state_from_url(url: str) -> bool:
    """Pure predicate: does this LinkedIn URL indicate an authenticated session?"""
    lowered = url.lower()
    if any(marker in lowered for marker in LOGGED_OUT_URL_MARKERS):
        return False
    return any(marker in lowered for marker in LOGGED_IN_URL_MARKERS)


class JobExtraction(BaseModel):
    """The agent's structured read of one job posting."""

    title: str = ""
    company: str = ""
    description: str = ""
    easy_apply: bool = False


_READ_JOB_TASK = (
    "Open this LinkedIn job posting and read it:\n"
    "URL: {url}\n\n"
    "Return the job title, the company name, the full job description text, and "
    'whether this posting offers LinkedIn "Easy Apply" (True/False). Read only — '
    "do not click Easy Apply, do not apply, and do not fill anything."
)


def build_read_job_task(url: str) -> str:
    """The browser-use task text for reading one job posting."""
    return _READ_JOB_TASK.format(url=url)


async def wait_for_login(
    browser: Any, timeout_seconds: int, *, poll_seconds: float = 1.0
) -> bool:
    """Poll the browser's current URL until it shows a session or the timeout ends."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        if login_state_from_url(await browser.get_current_page_url()):
            return True
        await asyncio.sleep(poll_seconds)
    return login_state_from_url(await browser.get_current_page_url())
