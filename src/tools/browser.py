"""browser-use wrapper for Task 1: log in, search jobs, select Easy Apply.

Task 1 launches a Chromium session, navigates to the LinkedIn login page, waits
for the user to log in (a human gate), then searches for the configured job
query and selects the **Easy Apply** filter on the results page. The interaction
uses browser-use's deterministic CDP actor API (``Page`` / ``Element``); no LLM
is involved.

The heavy ``browser`` extra is only needed for real runs, so this module is
imported lazily by the graph node:

    uv sync --extra browser
    uvx playwright install chromium
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from datetime import UTC, datetime

from src.configuration import Settings, load_settings
from src.state import Task1Outcome
from src.tools.linkedin import (
    build_jobs_search_url,
    is_logged_in_path,
    is_login_path,
    looks_like_jobs_search_input,
    pick_easy_apply_index,
)

_INSTALL_HINT = (
    "browser-use is not installed. Enable the optional extra:\n"
    "  uv sync --extra browser\n"
    "  uvx playwright install chromium"
)

# LinkedIn renders the Easy Apply filter toggle with this aria-label; the phrase
# check below is a fallback for markup variants. The exact "Easy Apply" phrase
# is required so an unrelated "Apply" control is never matched.
_EASY_APPLY_FILTER_SELECTORS = (
    "button[aria-label*='Easy Apply']",
    "[role='button'][aria-label*='Easy Apply']",
)

# The jobs search bar on the Jobs tab: a keywords input plus a submit button.
_JOBS_TAB_URL = "https://www.linkedin.com/jobs/"
_JOBS_SEARCH_INPUT_SELECTORS = (
    "input.jobs-search-box__keyboard-text-input",
    "input[aria-label='Search by title, skill, or company']",
    "input[aria-label*='title, skill, or company']",
    "input[aria-label*='Search jobs']",
    "input[placeholder*='title, skill, or company']",
)
_JOBS_SEARCH_SUBMIT_SELECTORS = (
    "button.jobs-search-box__submit-button",
    "button[aria-label='Search']",
    "button[type='submit']",
)

# How long to keep waiting for the results list to render after a search.
_RESULTS_WAIT_SECONDS = 20.0

_LOGIN_STATE_QUERY = """
() => JSON.stringify({
  path: location.pathname,
  nav: !!document.querySelector('.global-nav, nav.global-nav, #global-nav'),
  loginForm: !!document.querySelector(
    'form.login__form, input#username, input[name="session_key"]'
  )
})
"""

_RESULTS_QUERY = """
() => JSON.stringify({
  count: document.querySelectorAll(
    'li.jobs-search-results__list-item, li.scaffold-layout__list-item, '
    + 'div.job-card-container, div.jobs-search-results-list__list-item, '
    + 'ul.jobs-search__results-list > li'
  ).length
})
"""

_FILTER_QUERY = """
() => JSON.stringify({
  selected: (() => {
    const btn = document.querySelector('[aria-label*="Easy Apply"]');
    const pressed = btn ? btn.getAttribute('aria-pressed') : null;
    const inUrl = (location.search || '').indexOf('f_AL=true') !== -1;
    return pressed === 'true' || inUrl;
  })()
})
"""


def _require_browser_use():
    """Import browser-use on demand, with an actionable error if missing."""
    try:
        from browser_use import Browser
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(_INSTALL_HINT) from exc
    return Browser


async def _safe(awaitable, default=None):
    """Await ``awaitable``, returning ``default`` if it raises."""
    try:
        return await awaitable
    except Exception:  # noqa: BLE001 - best-effort probing of a live page
        return default


async def _pace(settings: Settings) -> None:
    """Pause between visible steps so a human can follow the run.

    A no-op unless ``AUTOJOB_SESSION_STEP_DELAY_SECONDS`` is set; used by the
    slow-motion demo/test run.
    """
    delay = settings.session.step_delay_seconds
    if delay:
        await asyncio.sleep(delay)


def _loads(raw: str) -> dict:
    """Parse a JSON payload returned by ``page.evaluate``, tolerating noise."""
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def build_browser(settings: Settings):
    """Build a Chromium session that persists logins in ``data/profile``."""
    Browser = _require_browser_use()
    settings.profile_dir.mkdir(parents=True, exist_ok=True)
    return Browser(
        headless=settings.session.headless,
        user_data_dir=str(settings.profile_dir),
        viewport=settings.session.viewport,
        user_agent=settings.session.user_agent,
    )


async def _wait_for_load(page, timeout_seconds: float) -> bool:
    """Poll until the page reports ``document.readyState == 'complete'``."""
    deadline = time.monotonic() + max(timeout_seconds, 0)
    while time.monotonic() < deadline:
        if await _safe(page.evaluate("() => document.readyState")) == "complete":
            return True
        await asyncio.sleep(0.25)
    return False


async def _element_label(element) -> str:
    """Best-effort accessible label for a candidate control."""
    for attribute in ("aria-label", "placeholder"):
        label = await _safe(element.get_attribute(attribute), "") or ""
        if label:
            return label
    return await _safe(element.evaluate("() => this.innerText"), "") or ""


async def _query_elements(page, selector: str) -> list:
    try:
        return list(await page.get_elements_by_css_selector(selector))
    except Exception:  # noqa: BLE001 - selector may not match in this DOM
        return []


async def _first_element(page, selectors):
    """Return the first matching element across ``selectors``, or ``None``."""
    for selector in selectors:
        elements = await _query_elements(page, selector)
        if elements:
            return elements[0]
    return None


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


async def type_jobs_search(page, query: str, settings: Settings) -> bool:
    """Open the Jobs tab, type ``query`` into the search bar, and submit it."""
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


async def results_count(page) -> int:
    """Number of job cards currently rendered on the search results page."""
    payload = _loads(await _safe(page.evaluate(_RESULTS_QUERY), ""))
    try:
        return int(payload.get("count") or 0)
    except (TypeError, ValueError):
        return 0


async def open_jobs_search(page, query: str, settings: Settings) -> tuple[bool, int, str]:
    """Type ``query`` into the jobs search bar and submit; return results info.

    Returns ``(found, count, url)``. If the search bar cannot be found, it falls
    back to navigating to the equivalent search URL so the run can still proceed.
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


async def find_easy_apply_filter(page):
    """Return the Easy Apply filter control, or ``None`` when absent."""
    candidates: list = []
    for selector in _EASY_APPLY_FILTER_SELECTORS:
        candidates.extend(await _query_elements(page, selector))

    labels = [await _element_label(element) for element in candidates]
    index = pick_easy_apply_index(labels)
    if index is not None:
        return candidates[index]

    # Fall back to scanning every interactive control on the page.
    controls = await _query_elements(page, "button, [role='button']")
    labels = [await _element_label(element) for element in controls]
    index = pick_easy_apply_index(labels)
    return controls[index] if index is not None else None


async def easy_apply_filter_selected(page) -> bool:
    """True when the Easy Apply filter is active on the results page."""
    payload = _loads(await _safe(page.evaluate(_FILTER_QUERY), ""))
    return bool(payload.get("selected"))


async def select_easy_apply_filter(page, settings: Settings) -> tuple[bool, str]:
    """Click the Easy Apply filter; return ``(selected, note)``."""
    note = ""
    button = await find_easy_apply_filter(page)
    if button is not None:
        await _safe(button.evaluate("() => this.scrollIntoView({block: 'center'})"))
        await _pace(settings)
        try:
            await button.click()
        except Exception as exc:  # noqa: BLE001 - fall through to the URL toggle
            note = f"Easy Apply filter click failed: {exc}"
        if settings.session.post_click_wait_seconds:
            await asyncio.sleep(settings.session.post_click_wait_seconds)

    if await easy_apply_filter_selected(page):
        return True, note

    # Fallback: the same toggle is exposed as the f_AL=true query parameter.
    current = await _safe(page.get_url(), "") or ""
    if current and "f_AL=true" not in current:
        separator = "&" if "?" in current else "?"
        await page.goto(f"{current}{separator}f_AL=true")
        await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)
        if await easy_apply_filter_selected(page):
            return True, note

    return False, note or "Easy Apply filter could not be selected"


async def capture_failure_screenshot(session, settings: Settings) -> str | None:
    """Write a full-page PNG for debugging and return its path."""
    settings.debug_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = settings.debug_dir / f"task1-failure-{stamp}.png"
    with contextlib.suppress(Exception):
        await session.take_screenshot(path=str(path), full_page=True)
    return str(path) if path.is_file() else None


async def run_task1(
    url: str,
    search_query: str,
    settings: Settings | None = None,
    progress=None,
) -> Task1Outcome:
    """Log in (waiting for the user if needed), search jobs, pick Easy Apply."""
    settings = settings or load_settings()
    notify = progress or (lambda _message: None)
    session = build_browser(settings)
    outcome = Task1Outcome(start_url=url, search_query=search_query)
    try:
        await session.start()
        page = await session.new_page()
        await page.goto(url)
        await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)
        await _pace(settings)

        outcome.already_logged_in = await is_logged_in(page)
        if outcome.already_logged_in:
            notify("Already logged in to LinkedIn.")
            outcome.logged_in = True
        else:
            notify(
                "Not logged in yet - please log in using the browser window. "
                f"Waiting up to {settings.session.login_timeout_seconds}s ..."
            )
            outcome.logged_in = await wait_for_login(
                page,
                timeout_seconds=settings.session.login_timeout_seconds,
                poll_seconds=settings.session.login_poll_seconds,
            )
            notify(
                "Login detected."
                if outcome.logged_in
                else "Login was not detected before the timeout."
            )
        await _pace(settings)

        if outcome.logged_in:
            await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)
            outcome.search_performed = True
            found, count, search_url = await open_jobs_search(page, search_query, settings)
            await _pace(settings)
            outcome.results_found = found
            outcome.results_count = count
            outcome.search_url = search_url
            if found:
                selected, note = await select_easy_apply_filter(page, settings)
                outcome.easy_apply_filter_selected = selected
                outcome.notes = note

        outcome.page_url = await _safe(page.get_url(), None)
        outcome.page_title = await _safe(page.get_title(), "") or ""

        if not (outcome.logged_in and outcome.results_found and outcome.easy_apply_filter_selected):
            outcome.screenshot_path = await capture_failure_screenshot(session, settings)
        return outcome
    finally:
        with contextlib.suppress(Exception):
            await session.kill()
