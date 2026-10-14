"""Task 1: log in to LinkedIn, search jobs, and select the Easy Apply filter.

This module owns Task 1's interactive browser flow, split out of
:mod:`src.tools.browser`:

1. Open the LinkedIn login page and wait for the human to log in (a human gate).
2. Type the configured job query (default "software engineer") into the jobs
   search bar and submit it.
3. Click LinkedIn's optional **"Try AI job search"** control when it is present,
   repeating the search after each click (capped), and
4. Select the **Easy Apply** filter on the results page.

The low-level browser primitives (pacing, safe probing, element resolution,
session construction, failure screenshots, and the shared Chromium profile
helpers) stay in :mod:`src.tools.browser`, which this module imports. The
interaction uses browser-use's deterministic CDP actor API (``Page`` /
``Element``); no LLM is involved.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from src.configuration import Settings, load_settings
from src.state import Task1Outcome
from src.tools.browser import (
    _APPLY_POLL_SECONDS,
    _RESULTS_WAIT_SECONDS,
    _append_note,
    _element_is_apply_button,
    _element_is_choice_control,
    _element_label,
    _first_element,
    _loads,
    _marker_element,
    _pace,
    _query_elements,
    _safe,
    _wait_for_load,
    build_browser,
    capture_failure_screenshot,
    results_count,
)
from src.tools.linkedin import (
    build_jobs_search_url,
    is_logged_in_path,
    is_login_path,
    looks_like_easy_apply,
    looks_like_jobs_search_input,
    pick_ai_job_search_index,
    pick_easy_apply_filter_index,
    pick_easy_apply_index,
)

# LinkedIn renders the Easy Apply filter toggle with this aria-label; the phrase
# check below is a fallback for markup variants. The exact "Easy Apply" phrase
# is required so an unrelated "Apply" control is never matched.
_EASY_APPLY_FILTER_SELECTORS = (
    "button[aria-label*='Easy Apply']",
    "[role='button'][aria-label*='Easy Apply']",
)

# LinkedIn's optional "Try AI job search" entry point (Task 1). Its markup varies
# (it can be a button, a link, a role=button/role=link, or a tab) and its
# accessible name can differ from its visible text, so we scan interactive
# controls at runtime and combine every label source. Only controls that mention
# "search" are returned; the precise AI match is applied in Python.
_AI_CANDIDATES_QUERY = r"""
() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-autojob-ai]').forEach(
    (el) => el.removeAttribute('data-autojob-ai')
  );
  const controls = document.querySelectorAll(
    'button, a, [role="button"], [role="link"], [role="tab"], '
    + 'input[type="button"], input[type="submit"]'
  );
  const out = [];
  let i = 0;
  controls.forEach((el) => {
    const rects = el.getClientRects();
    if (!rects.length) return; // skip hidden controls
    const label = norm(
      (el.getAttribute('aria-label') || '') + ' '
      + (el.getAttribute('title') || '') + ' '
      + (el.innerText || '') + ' '
      + (el.value || '')
    );
    if (!label || (label.toLowerCase().indexOf('search') === -1
        && label.toLowerCase().indexOf('ai') === -1
        && label.toLowerCase().indexOf('artificial') === -1)) return;
    const marker = 'ai' + (i++);
    el.setAttribute('data-autojob-ai', marker);
    out.push({ marker: marker, label: label });
  });
  return JSON.stringify({ candidates: out });
}
"""


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

# Safety cap on re-clicking "Try AI job search" when it reappears after each
# search, so a persistent control can never loop forever.
_MAX_AI_JOB_SEARCH_CLICKS = 3

_LOGIN_STATE_QUERY = """
() => JSON.stringify({
  path: location.pathname,
  nav: !!document.querySelector('.global-nav, nav.global-nav, #global-nav'),
  loginForm: !!document.querySelector(
    'form.login__form, input#username, input[name="session_key"]'
  )
})
"""

_FILTER_QUERY = """
() => JSON.stringify({
  selected: (() => {
    const btn = document.querySelector(
      '[id="searchFilter_applyWithLinkedin"], [aria-label*="Easy Apply"]'
    );
    if (!btn) return (location.search || '').indexOf('f_AL=true') !== -1;
    // The real Easy Apply filter pill is role="radio" with aria-checked; other
    // variants expose aria-pressed. Neither is present on a job's apply button.
    const checked = btn.getAttribute('aria-checked');
    const pressed = btn.getAttribute('aria-pressed');
    const inUrl = (location.search || '').indexOf('f_AL=true') !== -1;
    return checked === 'true' || pressed === 'true' || inUrl;
  })()
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


async def _settle_after_click(page, settings: Settings) -> None:
    """Wait for the page to finish loading after a click.

    The flow clicks **one** control at a time. A click can navigate or reload
    the page, so before the next control is touched the run pauses for
    ``post_click_wait_seconds`` (giving the navigation time to commit) and then
    waits until ``document.readyState`` is ``'complete'``. Without this the next
    step interacts with a half-loaded page, which shows up as several controls
    being clicked at once.
    """
    if settings.session.post_click_wait_seconds:
        await asyncio.sleep(settings.session.post_click_wait_seconds)
    await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)


async def type_jobs_search(page, query: str, settings: Settings) -> bool:
    """Type ``query`` into the jobs search bar and submit it.

    When the jobs search bar is already on the page (e.g. after the first search)
    it is used as-is, like a real user typing. LinkedIn may reload or navigate as
    it normally does when a search is submitted. The Jobs tab is opened once when
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


async def find_easy_apply_filter(page):
    """Return the Easy Apply *filter* toggle, or ``None`` when absent.

    The results page shows two controls whose accessible name contains "Easy
    Apply": the results filter pill (``id="searchFilter_applyWithLinkedin"``,
    ``role="radio"`` with ``aria-checked``, class ``search-reusables__filter-pill-button``
    — e.g. the pill beside "Backend" in the filter bar) and the blue "Easy Apply"
    apply button on a job (``jobs-apply-button`` / ``artdeco-button--primary``,
    blue background). They share the label text, so they are told apart by
    structure: the filter is a choice toggle (``role="radio"``/``aria-checked`` or
    ``aria-pressed``) and is never a ``jobs-apply-button``.

    A choice-toggle filter is always preferred; when there is no toggle, only a
    control whose label explicitly names the filter is accepted. When neither
    exists the caller falls back to the ``f_AL=true`` URL toggle, so a job's
    apply button is never clicked as if it were the filter.
    """
    candidates: list = []
    seen: set[int] = set()
    for selector in _EASY_APPLY_FILTER_SELECTORS + ("button, [role='button']",):
        for element in await _query_elements(page, selector):
            if id(element) in seen:
                continue
            seen.add(id(element))
            label = await _element_label(element)
            if looks_like_easy_apply(label) and not await _element_is_apply_button(element):
                candidates.append((element, label))

    if not candidates:
        return None

    # The filter pill is a choice toggle; the blue apply button is not.
    toggles = [
        (el, label) for el, label in candidates if await _element_is_choice_control(el)
    ]
    if toggles:
        labels = [label for _el, label in toggles]
        index = pick_easy_apply_filter_index(labels)
        if index is None:
            index = pick_easy_apply_index(labels)
        if index is not None:
            return toggles[index][0]

    # No toggle: only accept a control whose label names the filter, so a job's
    # bare "Easy Apply" apply button is never mistaken for it.
    labels = [label for _el, label in candidates]
    index = pick_easy_apply_filter_index(labels)
    if index is not None:
        return candidates[index][0]

    return None


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
        # The filter click re-renders/navigates the results page; wait for it to
        # settle before verifying, so the next step never clicks a control on a
        # half-loaded page.
        await _settle_after_click(page, settings)

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


async def _read_ai_candidates(page) -> list[dict]:
    payload = _loads(await _safe(page.evaluate(_AI_CANDIDATES_QUERY), ""))
    return list(payload.get("candidates") or [])


async def find_ai_job_search_button(page):
    """Return LinkedIn's "Try AI job search" control, or ``None`` when absent.

    Discovery is runtime and markup-agnostic: a JS scan collects visible
    interactive controls whose combined label mentions "search" or "AI", then the
    pure :func:`looks_like_ai_job_search` predicate picks the AI one.
    """
    candidates = await _read_ai_candidates(page)
    labels = [candidate.get("label", "") for candidate in candidates]
    index = pick_ai_job_search_index(labels)
    if index is None:
        return None
    marker = candidates[index].get("marker")
    return await _marker_element(page, "data-autojob-ai", marker) if marker else None


async def read_ai_job_search_candidates(page) -> list[str]:
    """Labels of the controls the AI scan saw, for diagnosing a miss."""
    return [candidate.get("label", "") for candidate in await _read_ai_candidates(page)]


async def wait_for_ai_job_search_button(page, settings: Settings):
    """Wait briefly for the optional AI job search control; return it or ``None``."""
    deadline = time.monotonic() + settings.session.ai_search_timeout_seconds
    button = await find_ai_job_search_button(page)
    while button is None and time.monotonic() < deadline:
        await asyncio.sleep(_APPLY_POLL_SECONDS)
        button = await find_ai_job_search_button(page)
    return button


async def click_ai_job_search(page, settings: Settings, button=None) -> bool:
    """Click LinkedIn's optional "Try AI job search" control when present.

    The control often navigates/reloads the page. A navigating click can make
    ``Element.click()`` raise *after* the navigation has already started (the CDP
    execution context is torn down), which is not a failed click. So a raised
    exception is discarded and success is judged from whether the URL changed,
    and the page load is awaited either way so the caller can repeat the search
    on the new page.
    """
    if button is None:
        button = await find_ai_job_search_button(page)
    if button is None:
        return False

    url_before = await _safe(page.get_url(), "") or ""
    await _safe(button.evaluate("() => this.scrollIntoView({block: 'center'})"))
    await _pace(settings)

    clicked = False
    try:
        await button.click()
        clicked = True
    except Exception:  # noqa: BLE001 - a navigating click may raise; judged below
        clicked = False
    if settings.session.post_click_wait_seconds:
        await asyncio.sleep(settings.session.post_click_wait_seconds)
    await _pace(settings)

    # The click may have triggered a navigation/reload; wait for it before the
    # caller repeats the search, and treat a changed URL as a successful click.
    await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)
    url_after = await _safe(page.get_url(), "") or ""
    if url_after and url_after != url_before:
        clicked = True
    return clicked


async def run_ai_job_search_detour(
    page,
    search_query: str,
    settings: Settings,
    notify,
    outcome: Task1Outcome,
) -> None:
    """Click the optional "Try AI job search" control and repeat the search.

    The control is optional: when it is absent the search is performed only once
    and this returns without changing the outcome. When it is present, each click
    is followed by a repeat "software engineer" search, and the click/repeat pair
    is retried while the control reappears — up to ``_MAX_AI_JOB_SEARCH_CLICKS`` so
    a persistent control can never loop forever. Searching follows LinkedIn's
    normal behaviour and may reload or navigate the page.

    Once the control is clicked the run stays in LinkedIn's AI (semantic) search
    mode: it never navigates back to the classic jobs search. A repeat search that
    returns no results simply ends the re-click loop and the outcome reflects the
    AI search.
    """
    for _ in range(_MAX_AI_JOB_SEARCH_CLICKS):
        ai_button = await wait_for_ai_job_search_button(page, settings)
        if ai_button is None:
            break

        outcome.ai_job_search_present = True
        notify("Task 1: 'Try AI job search' button found; clicking it.")
        if not await click_ai_job_search(page, settings, ai_button):
            outcome.notes = _append_note(
                outcome.notes,
                "Try AI job search button was present but could not be clicked",
            )
            return

        outcome.ai_job_search_clicked = True
        outcome.ai_job_search_clicks += 1
        notify("Task 1: repeating the job search after AI job search.")
        found, count, url = await open_jobs_search(page, search_query, settings)
        outcome.results_found = found
        outcome.results_count = count
        outcome.search_url = url
        if not found:
            # Stay in the AI mode: a repeat that returns nothing just ends the
            # re-click loop. Never fall back to the classic search.
            break

    if not outcome.ai_job_search_present:
        # Nothing matched. Record the labels the scan actually saw so a real-run
        # miss (different wording/markup) is diagnosable.
        outcome.ai_job_search_candidates = await read_ai_job_search_candidates(page)
        if outcome.ai_job_search_candidates:
            outcome.notes = _append_note(
                outcome.notes,
                "AI job search not matched; controls seen: "
                + "; ".join(outcome.ai_job_search_candidates[:10]),
            )


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
            await run_ai_job_search_detour(page, search_query, settings, notify, outcome)
            selected, note = await select_easy_apply_filter(page, settings)
            outcome.easy_apply_filter_selected = selected
            outcome.notes = _append_note(outcome.notes, note)

    outcome.page_url = await _safe(page.get_url(), None)
    outcome.page_title = await _safe(page.get_title(), "") or ""
    return outcome


def _task1_ok(outcome: Task1Outcome) -> bool:
    return bool(outcome.logged_in and outcome.results_found and outcome.easy_apply_filter_selected)


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
