"""`session` (LinkedIn page operations) — search and modal interaction primitives.

Implemented in Task 3 (login detection), Task 5 (read a job, detect Easy Apply),
Task 12 (search results) and Task 13 (Easy Apply modal steps). Selectors used for
*reading* live here; fill selectors live in ``src/nodes/fill.py``.

Every call routes through ``src/tools/guard.py`` (SPEC.md §8).
"""

from __future__ import annotations

import time

from playwright.sync_api import Page

LOGIN_URL = "https://www.linkedin.com/login"
FEED_URL = "https://www.linkedin.com/feed/"
MYNETWORK_URL = "https://www.linkedin.com/mynetwork/"

# URL fragments that identify an authenticated session vs. a login wall.
LOGGED_IN_URL_MARKERS = ("/feed", "/mynetwork")
LOGGED_OUT_URL_MARKERS = ("/login", "/authwall", "/checkpoint", "/uas/")


def login_state_from_url(url: str) -> bool:
    """Pure predicate: does this LinkedIn URL indicate an authenticated session?

    Kept free of Playwright so it is unit-testable without a browser (SPEC.md §6).
    """
    lowered = url.lower()
    if any(marker in lowered for marker in LOGGED_OUT_URL_MARKERS):
        return False
    return any(marker in lowered for marker in LOGGED_IN_URL_MARKERS)


def is_logged_in(page: Page) -> bool:
    """Best-effort check that the current page reflects a live session."""
    return login_state_from_url(page.url)


def wait_for_login(page: Page, timeout_seconds: int, *, poll_seconds: float = 1.0) -> bool:
    """Block until the page shows an authenticated session or the timeout elapses."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if is_logged_in(page):
            return True
        time.sleep(poll_seconds)
    return is_logged_in(page)
