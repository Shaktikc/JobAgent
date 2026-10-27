"""Task 1's jobs search bar, login gate, and results wait.

Owns the runtime discovery/typing of the jobs search input (including
LinkedIn's AI "Describe the job you want" prompt), the login-state check, and
the results wait. Uses the shared browser primitives and the
one-control-at-a-time settle from :mod:`.common`; no LLM is involved.
"""

from __future__ import annotations

import asyncio
import time

from src.configuration import Settings
from src.tools.browser import (
    _RESULTS_WAIT_SECONDS,
    _first_element,
    _loads,
    _pace,
    _query_elements,
    _safe,
    _wait_for_load,
    results_count,
)
from src.tools.linkedin import (
    build_jobs_search_url,
    is_logged_in_path,
    is_login_path,
    looks_like_jobs_search_input,
)
from src.tools.linkedin_search.common import _settle_after_click

# The jobs search bar on the Jobs tab: a keywords input plus a submit button.
_JOBS_TAB_URL = "https://www.linkedin.com/jobs/"
_JOBS_SEARCH_INPUT_SELECTORS = (
    "input.jobs-search-box__keyboard-text-input",
    "input[aria-label='Search by title, skill, or company']",
    "input[aria-label*='title, skill, or company']",
    "input[aria-label*='Search jobs']",
    "input[placeholder*='title, skill, or company']",
    # LinkedIn's AI job search page prompt ("Describe the job you want").
    "input[aria-label*='Describe the job']",
    "input[placeholder*='Describe the job']",
)
_JOBS_SEARCH_SUBMIT_SELECTORS = (
    "button.jobs-search-box__submit-button",
    "button[aria-label='Search']",
    "button[type='submit']",
)

_LOGIN_STATE_QUERY = """
() => JSON.stringify({
  path: location.pathname,
  nav: !!document.querySelector('.global-nav, nav.global-nav, #global-nav'),
  loginForm: !!document.querySelector(
    'form.login__form, input#username, input[name="session_key"]'
  )
})
"""


async def find_jobs_search_input(page):
    """Return the jobs search bar's keywords input, or ``None`` when absent."""
    field = await _first_element(page, _JOBS_SEARCH_INPUT_SELECTORS)
    if field is not None:
        return field

    # Fall back to scanning every input and matching its label/placeholder.
    for element in await _query_elements(page, "input"):
        if looks_like_jobs_search_input(await _element_label(element)):
            return element
    return None


async def _element_label(element) -> str:
    """Best-effort accessible label for a candidate control."""
    for attribute in ("aria-label", "placeholder"):
        label = await _safe(element.get_attribute(attribute), "") or ""
        if label:
            return label
    return await _safe(element.evaluate("() => this.innerText"), "") or ""


async def type_jobs_search(page, query: str, settings: Settings) -> bool:
    """Type ``query`` into the jobs search bar and submit it.

    When the search bar is already on the page (e.g. after the first search) it
    is used as-is, like a real user typing. LinkedIn may reload or navigate as it
    normally does when a search is submitted. The Jobs tab is opened once when
    no search bar is present (e.g. when starting from the feed).
    """
    field = await find_jobs_search_input(page)
    if field is None:
        await page.goto(_JOBS_TAB_URL)
        await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)
        await _pace(settings)
        field = await find_jobs_search_input(page)
    if field is None:
        return False

    await _safe(field.evaluate("() => this.scrollIntoView({block: 'center'})"))
    try:
        await field.fill(query)
    except Exception:  # noqa: BLE001 - fall back to URL-based search
        return False
    await _pace(settings)

    submit = await _first_element(page, _JOBS_SEARCH_SUBMIT_SELECTORS)
    if submit is not None:
        await _safe(submit.click())
    else:
        # The field is still focused from fill(); Enter submits the search.
        await _safe(page.press("Enter"))
    # Exactly one control was activated. The search navigates/reloads the page, so
    # wait for it to finish loading before the caller reads results or clicks the
    # next control; otherwise the next step lands on a half-loaded page.
    await _settle_after_click(page, settings)
    await _pace(settings)
    return True


async def is_logged_in(page) -> bool:
    """True when the current page indicates an authenticated session."""
    payload = _loads(await _safe(page.evaluate(_LOGIN_STATE_QUERY), ""))
    path = payload.get("path") or ""
    if is_logged_in_path(path):
        return True
    if is_login_path(path):
        return False
    # Ambiguous page (e.g. root): fall back to the global nav / login form.
    return bool(payload.get("nav")) and not payload.get("loginForm")


async def wait_for_login(page, *, timeout_seconds: float, poll_seconds: float) -> bool:
    """Poll until the user has logged in, or the timeout elapses."""
    if await is_logged_in(page):
        return True
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        await asyncio.sleep(poll_seconds)
        if await is_logged_in(page):
            return True
    return False


async def open_jobs_search(page, query: str, settings: Settings) -> tuple[bool, int, str]:
    """Type ``query`` into the jobs search bar and submit; return results info.

    Returns ``(found, count, url)``. Searching behaves like LinkedIn's default:
    the page may reload or navigate. When the search bar cannot be found the run
    falls back to navigating to the equivalent search URL.
    """
    typed = await type_jobs_search(page, query, settings)
    if not typed:
        await page.goto(build_jobs_search_url(query))
        await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)

    count = await results_count(page)
    deadline = time.monotonic() + _RESULTS_WAIT_SECONDS
    while count == 0 and time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        count = await results_count(page)

    current_url = await _safe(page.get_url(), "") or ""
    return count > 0, count, current_url


__all__ = [
    "_JOBS_SEARCH_INPUT_SELECTORS",
    "_JOBS_SEARCH_SUBMIT_SELECTORS",
    "_JOBS_TAB_URL",
    "_LOGIN_STATE_QUERY",
    "_element_label",
    "find_jobs_search_input",
    "is_logged_in",
    "open_jobs_search",
    "type_jobs_search",
    "wait_for_login",
]
