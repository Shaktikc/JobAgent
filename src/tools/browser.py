"""browser-use wrapper for the LinkedIn agent (Task 1 + Task 2).

Task 1 launches a Chromium session, navigates to the LinkedIn login page, waits
for the user to log in (a human gate), then types the configured job query into
the jobs search bar and selects the **Easy Apply** filter on the results page.

Task 2 continues in the *same* session: it reads the job list left open by Task
1, opens the first job that offers Easy Apply (skipping external-apply jobs),
clicks its **Easy Apply** button, and confirms the application form opened. The
application is never submitted.

The interaction uses browser-use's deterministic CDP actor API (``Page`` /
``Element``); no LLM is involved.

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
from src.state import AgentOutcome, Task1Outcome, Task2Outcome
from src.tools.linkedin import (
    build_jobs_search_url,
    is_logged_in_path,
    is_login_path,
    looks_like_apply_modal,
    looks_like_easy_apply_action,
    looks_like_jobs_search_input,
    pick_easy_apply_action_index,
    pick_easy_apply_filter_index,
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

# Job cards in the left-hand search-results list (Task 2).
_JOB_CARD_SELECTORS = (
    "li.jobs-search-results__list-item",
    "li.scaffold-layout__list-item",
    "div.job-card-container",
    "ul.jobs-search__results-list > li",
)

# The job's apply button in the right-hand details pane (Task 2). Its label is
# "Easy Apply" for Easy Apply jobs and "Apply" for external ones.
_JOB_DETAILS_APPLY_SELECTORS = (
    "div.jobs-search__job-details--container button.jobs-apply-button",
    "div.scaffold-layout__detail button.jobs-apply-button",
    "div.job-view-layout button.jobs-apply-button",
    "div.jobs-details button.jobs-apply-button",
    "button.jobs-apply-button",
)

# How long to keep waiting for the results list to render after a search.
_RESULTS_WAIT_SECONDS = 20.0
# Poll interval used while waiting for the details pane / apply modal.
_APPLY_POLL_SECONDS = 0.5

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

_APPLY_MODAL_QUERY = """
() => {
  const modal = document.querySelector(
    'div.jobs-easy-apply-modal, div[data-test-modal-container], '
    + 'div[role="dialog"].artdeco-modal, .artdeco-modal--layer-default'
  );
  return JSON.stringify({
    open: !!modal,
    text: modal ? (modal.innerText || '').slice(0, 1000) : ''
  });
}
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


def _first_line(text: str) -> str:
    """First non-empty line of ``text`` (a job card's title), truncated."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:200]
    return ""


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
    """Return the Easy Apply *filter* control, or ``None`` when absent."""
    candidates: list = []
    for selector in _EASY_APPLY_FILTER_SELECTORS:
        candidates.extend(await _query_elements(page, selector))

    labels = [await _element_label(element) for element in candidates]
    # Prefer a control whose label mentions "filter" so a job's Easy Apply
    # *button* (also matching ``*='Easy Apply'``) is not mistaken for the filter.
    index = pick_easy_apply_filter_index(labels)
    if index is None:
        index = pick_easy_apply_index(labels)
    if index is not None:
        return candidates[index]

    # Fall back to scanning every interactive control on the page.
    controls = await _query_elements(page, "button, [role='button']")
    labels = [await _element_label(element) for element in controls]
    index = pick_easy_apply_filter_index(labels)
    if index is None:
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


async def read_job_cards(page) -> list:
    """Return the job cards currently shown in the search results list."""
    for selector in _JOB_CARD_SELECTORS:
        cards = await _query_elements(page, selector)
        if cards:
            return cards
    return []


async def find_job_apply_button(page) -> tuple:
    """Return ``(element, label)`` for the details pane's apply button, or ``(None, "")``."""
    button = await _first_element(page, _JOB_DETAILS_APPLY_SELECTORS)
    if button is not None:
        return button, await _element_label(button)

    # Fall back to scanning interactive controls for an Easy Apply *action*
    # (an Easy Apply label that is not the results filter).
    controls = await _query_elements(page, "button, [role='button']")
    labels = [await _element_label(element) for element in controls]
    index = pick_easy_apply_action_index(labels)
    return (controls[index], labels[index]) if index is not None else (None, "")


async def wait_for_job_apply_button(page, settings: Settings) -> tuple:
    """Wait for the details pane's apply button to appear; return ``(element, label)``."""
    deadline = time.monotonic() + settings.session.easy_apply_timeout_seconds
    button, label = await find_job_apply_button(page)
    while button is None and time.monotonic() < deadline:
        await asyncio.sleep(_APPLY_POLL_SECONDS)
        button, label = await find_job_apply_button(page)
    return button, label


async def read_apply_modal(page) -> tuple[bool, str]:
    """Return ``(open, text)`` for the Easy Apply application form/modal."""
    payload = _loads(await _safe(page.evaluate(_APPLY_MODAL_QUERY), ""))
    if not payload.get("open"):
        return False, ""
    text = payload.get("text") or ""
    # An unrelated dialog should not count; require recognisable Easy Apply text
    # when the modal exposes any.
    return (not text or looks_like_apply_modal(text)), text


async def wait_for_easy_apply_modal(page, settings: Settings) -> tuple[bool, str]:
    """Wait for the Easy Apply application form to open; return ``(open, text)``."""
    deadline = time.monotonic() + settings.session.easy_apply_timeout_seconds
    opened, text = await read_apply_modal(page)
    while not opened and time.monotonic() < deadline:
        await asyncio.sleep(_APPLY_POLL_SECONDS)
        opened, text = await read_apply_modal(page)
    return opened, text


async def capture_failure_screenshot(
    session, settings: Settings, name: str = "task1"
) -> str | None:
    """Write a full-page PNG for debugging and return its path."""
    settings.debug_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = settings.debug_dir / f"{name}-failure-{stamp}.png"
    with contextlib.suppress(Exception):
        await session.take_screenshot(path=str(path), full_page=True)
    return str(path) if path.is_file() else None


async def _task1_on_page(
    page,
    url: str,
    search_query: str,
    settings: Settings,
    notify,
) -> Task1Outcome:
    """Run Task 1 steps on an already-open page (no session lifecycle)."""
    outcome = Task1Outcome(start_url=url, search_query=search_query)
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
            "Login detected." if outcome.logged_in else "Login was not detected before the timeout."
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
    return outcome


async def _task2_on_page(page, settings: Settings, notify) -> Task2Outcome:
    """Run Task 2 steps on the results page left open by Task 1."""
    outcome = Task2Outcome()

    cards = await read_job_cards(page)
    deadline = time.monotonic() + _RESULTS_WAIT_SECONDS
    while not cards and time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        cards = await read_job_cards(page)
    outcome.jobs_seen = len(cards) or await results_count(page)
    notify(f"Task 2: {outcome.jobs_seen} job(s) in the list.")
    await _pace(settings)

    for index, card in enumerate(cards):
        title = _first_line(await _element_label(card))
        outcome.job_index = index
        outcome.job_title = title
        notify(f"Task 2: opening job {index + 1}: {title or '(untitled)'}")

        await _safe(card.evaluate("() => this.scrollIntoView({block: 'center'})"))
        try:
            await card.click()
        except Exception as exc:  # noqa: BLE001 - try the next job
            outcome.notes = f"Could not open job {index + 1}: {exc}"
            outcome.skipped_jobs += 1
            continue
        if settings.session.post_click_wait_seconds:
            await asyncio.sleep(settings.session.post_click_wait_seconds)
        await _pace(settings)

        button, label = await wait_for_job_apply_button(page, settings)
        if button is None or not looks_like_easy_apply_action(label):
            outcome.skipped_jobs += 1
            notify("Task 2: no Easy Apply for this job; skipping.")
            continue

        outcome.easy_apply_button_found = True
        await _safe(button.evaluate("() => this.scrollIntoView({block: 'center'})"))
        await _pace(settings)
        try:
            await button.click()
        except Exception as exc:  # noqa: BLE001 - try the next job
            outcome.notes = f"Easy Apply click failed: {exc}"
            continue
        outcome.easy_apply_clicked = True
        await _pace(settings)

        opened, modal_text = await wait_for_easy_apply_modal(page, settings)
        outcome.application_form_opened = opened
        outcome.modal_text = modal_text
        if opened:
            notify("Task 2: Easy Apply application form opened.")
            break
        outcome.notes = "Easy Apply form did not open after the click"

    outcome.page_url = await _safe(page.get_url(), None)
    outcome.page_title = await _safe(page.get_title(), "") or ""
    return outcome


def _task1_ok(outcome: Task1Outcome) -> bool:
    return bool(outcome.logged_in and outcome.results_found and outcome.easy_apply_filter_selected)


def _task2_ok(outcome: Task2Outcome) -> bool:
    return bool(outcome.easy_apply_clicked and outcome.application_form_opened)


async def run_task1(
    url: str,
    search_query: str,
    settings: Settings | None = None,
    progress=None,
) -> Task1Outcome:
    """Run Task 1 only: log in (waiting for the user if needed), search, filter."""
    settings = settings or load_settings()
    notify = progress or (lambda _message: None)
    session = build_browser(settings)
    try:
        await session.start()
        page = await session.new_page()
        outcome = await _task1_on_page(page, url, search_query, settings, notify)
        if not _task1_ok(outcome):
            outcome.screenshot_path = await capture_failure_screenshot(session, settings, "task1")
        return outcome
    finally:
        with contextlib.suppress(Exception):
            await session.kill()


async def run_agent(
    url: str,
    search_query: str,
    settings: Settings | None = None,
    progress=None,
) -> AgentOutcome:
    """Run Task 1 then Task 2 in one browser session.

    Task 2 has no inputs of its own: it acts on the job list Task 1 leaves open,
    so both run against the same page. Task 2 is skipped when Task 1 fails.
    """
    settings = settings or load_settings()
    notify = progress or (lambda _message: None)
    session = build_browser(settings)
    task1 = Task1Outcome(start_url=url, search_query=search_query)
    task2 = Task2Outcome()
    try:
        await session.start()
        page = await session.new_page()

        task1 = await _task1_on_page(page, url, search_query, settings, notify)
        if not _task1_ok(task1):
            notify("Task 1 did not complete; skipping Task 2.")
            task2.notes = "Task 1 did not complete; Task 2 was skipped."
            task1.screenshot_path = await capture_failure_screenshot(session, settings, "task1")
        else:
            task2 = await _task2_on_page(page, settings, notify)
            if not _task2_ok(task2):
                task2.screenshot_path = await capture_failure_screenshot(session, settings, "task2")
        return AgentOutcome(task1=task1, task2=task2)
    finally:
        with contextlib.suppress(Exception):
            await session.kill()
