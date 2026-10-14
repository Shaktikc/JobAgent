"""Task 2: select a job from the search results and open its Easy Apply form.

This module owns Task 2's interactive browser flow, split out of
:mod:`src.tools.browser`:

1. Read the job cards currently displayed in the search-results list left open by
   Task 1.
2. Open the first (or next) job that offers **Easy Apply**, skipping jobs already
   marked "Applied" when ``settings.session.skip_applied`` is set.
3. Click the details pane's **Easy Apply** button and
4. Confirm the Easy Apply application form/modal opened.

Task 6's applied-job detection (classify a card as **Applied**, record the skip,
and produce the "no unapplied job" note) lives in
:mod:`src.tools.linkedin_skip_applied`; this module calls it while scanning.
Task 7's pagination lives in :mod:`src.tools.linkedin_pagination`: when *every*
card on the current page is Applied, this module advances the results list to the
next page (up to ``_MAX_RESULT_PAGES``) and scans it again.

The low-level browser primitives (pacing, safe probing, element resolution, the
shared AI/semantic job-card scanner, failure screenshots, and the session /
profile management) stay in :mod:`src.tools.browser`, which this module imports.
The interaction uses browser-use's deterministic CDP actor API (``Page`` /
``Element``); no LLM is involved.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass

from src.configuration import Settings
from src.state import Task2Outcome
from src.tools.browser import (
    _APPLY_POLL_SECONDS,
    _JOB_CARD_ATTR,
    _RESULTS_WAIT_SECONDS,
    FIND_APPLY_ROOT_JS,
    _append_note,
    _element_label,
    _first_element,
    _loads,
    _mark_ai_job_cards,
    _pace,
    _query_elements,
    _safe,
    results_count,
)
from src.tools.linkedin import (
    looks_like_apply_modal,
    looks_like_easy_apply_action,
    looks_like_job_card_label,
    pick_easy_apply_action_index,
)
from src.tools.linkedin_pagination import _MAX_RESULT_PAGES, go_to_next_page
from src.tools.linkedin_skip_applied import applied_skip_note, skip_applied_card

# Job cards in the left-hand search-results list (Task 2). This mirrors the
# selector union :func:`results_count` uses, so a card style that ``results_count``
# can see is never invisible to ``read_job_cards`` (which would stall the run).
_JOB_CARD_SELECTORS = (
    "li.jobs-search-results__list-item",
    "li.scaffold-layout__list-item",
    "div.job-card-container",
    "div.jobs-search-results-list__list-item",
    "ul.jobs-search__results-list > li",
    # AI/semantic results page (origin=SEMANTIC_SEARCH_LANDING_PAGE): the job
    # cards are rendered as div[role="button"], not classic <li> items. Their
    # accessible name starts with the job title and repeats it (see
    # _JOB_CARD_ATTR for the marker that proves a div is a job card).
    "[data-autojob-card]",
)

# How many job cards to try before giving up on the results page. The list is
# re-read after every click (LinkedIn re-renders it), so this is only a safety cap.
_MAX_JOB_ATTEMPTS = 40

# The job's apply button in the right-hand details pane (Task 2). Its label is
# "Easy Apply" for Easy Apply jobs and "Apply"/"Apply on company website" for
# external ones. The AI/semantic results layout renders the button with hashed
# CSS-in-JS classes (no ``jobs-apply-button``), so also match its accessible
# label: ``^="Easy Apply to"`` finds "Easy Apply to this job" / "Easy Apply to
# <job> at <company>", and deliberately does not match the results filter pill
# ("Easy Apply filter.").
_JOB_DETAILS_APPLY_SELECTORS = (
    "div.jobs-search__job-details--container button.jobs-apply-button",
    "div.scaffold-layout__detail button.jobs-apply-button",
    "div.job-view-layout button.jobs-apply-button",
    "div.jobs-details button.jobs-apply-button",
    "button.jobs-apply-button",
    "[data-live-test-job-apply-button]",
    'button[aria-label^="Easy Apply to" i]',
    'a[aria-label^="Easy Apply to" i]',
)

_APPLY_MODAL_QUERY = (
    "() => {\n"
    + FIND_APPLY_ROOT_JS
    + "\n  const root = findApplyRoot();\n"
    + "  return JSON.stringify({\n"
    + "    open: !!root,\n"
    + "    text: root ? (root.innerText || '').slice(0, 1000) : ''\n"
    + "  });\n"
    + "}\n"
)


def _first_line(text: str) -> str:
    """First non-empty line of ``text`` (a job card's title), truncated."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:200]
    return ""


def _job_key(title: str, index: int) -> str:
    """Stable identity for a results-list job (its title, or index when blank)."""
    normalized = re.sub(r"\s+", " ", (title or "").strip().lower())
    return normalized or f"#{index}"


async def read_job_cards(page) -> list:
    """Return the job cards currently shown in the search results list."""
    # Ensure AI/semantic job cards are marked so [data-autojob-card] resolves them.
    await _mark_ai_job_cards(page)
    for selector in _JOB_CARD_SELECTORS:
        cards = await _query_elements(page, selector)
        if cards:
            return cards
    return []


async def _element_is_job_card(element) -> bool:
    """True when ``element`` is a job card, not the details pane's apply button.

    AI/semantic job cards are ``div[role="button"]`` marked with
    ``data-autojob-card`` (see :data:`_JOB_CARD_ATTR`). Their accessible text
    also carries "Easy Apply", so without this check the fallback scan would
    mistake the first card for the apply button and click it instead of the blue
    "Easy Apply" button (the Task 2 bug).

    A real apply button is a ``<button>`` and is never excluded by the label
    heuristic, so a job whose title/company contains a location word (e.g.
    "Remote") is still matched.
    """
    if await _safe(element.get_attribute(_JOB_CARD_ATTR), None) is not None:
        return True
    tag = await _safe(element.evaluate("() => this.tagName"), "") or ""
    if str(tag).upper() == "BUTTON":
        return False
    return looks_like_job_card_label(await _element_label(element))


async def find_job_apply_button(page) -> tuple:
    """Return ``(element, label)`` for the details pane's apply button, or ``(None, "")``."""
    # Ensure AI/semantic job cards are marked so the fallback scan below can
    # exclude them: a job card's "Easy Apply" badge is not the apply button.
    await _mark_ai_job_cards(page)
    button = await _first_element(page, _JOB_DETAILS_APPLY_SELECTORS)
    if button is not None:
        return button, await _element_label(button)

    # Fall back to scanning interactive controls for an Easy Apply *action*
    # (an Easy Apply label that is not the results filter). Job cards are
    # excluded — their text also contains "Easy Apply" but they are not the
    # blue apply button.
    controls = await _query_elements(page, "button, [role='button']")
    labels = [await _element_label(element) for element in controls]
    candidates = [
        (element, label)
        for element, label in zip(controls, labels)
        if looks_like_easy_apply_action(label) and not await _element_is_job_card(element)
    ]
    index = pick_easy_apply_action_index([label for _element, label in candidates])
    return (candidates[index][0], candidates[index][1]) if index is not None else (None, "")


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


@dataclass
class _PageScan:
    """What one pass over a single results page produced (Tasks 2 and 6)."""

    opened: bool = False
    cards_seen: int = 0
    applied_skipped: int = 0


async def _wait_for_cards(page) -> list:
    """Wait for the results list to render and return its job cards."""
    cards = await read_job_cards(page)
    deadline = time.monotonic() + _RESULTS_WAIT_SECONDS
    while not cards and time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        cards = await read_job_cards(page)
    return cards


async def _scan_page(
    page,
    settings: Settings,
    notify,
    outcome: Task2Outcome,
    tried: set[str],
    applied_seen: set[str],
    capture=None,
) -> _PageScan:
    """Scan one results page: skip Applied cards and open the first unapplied job.

    The results list is re-read on every attempt: clicking a card on LinkedIn's
    semantic results page navigates to the job and re-renders the list, which
    detaches every previously resolved card element. Reusing those stale handles
    silently clicks nothing, leaving the details pane on the first job so every
    later job is skipped. Re-reading gives fresh handles each time.
    """
    scan = _PageScan()
    before_applied = outcome.applied_jobs_skipped
    cards = await _wait_for_cards(page)
    scan.cards_seen = len(cards)

    for _attempt in range(_MAX_JOB_ATTEMPTS):
        # Re-read the list so every card handle is fresh (the previous click may
        # have navigated and re-rendered it).
        cards = await read_job_cards(page)
        if not cards:
            # LinkedIn can briefly leave the list empty while it swaps layouts
            # (classic -> AI/semantic) after the "Try AI job search" detour.
            # Wait for it to settle instead of stopping with nothing to open.
            settle_deadline = time.monotonic() + _RESULTS_WAIT_SECONDS
            while not cards and time.monotonic() < settle_deadline:
                await asyncio.sleep(0.5)
                cards = await read_job_cards(page)
            if not cards:
                break

        candidate = None
        for index, card in enumerate(cards):
            label = await _element_label(card)
            title = _first_line(label)
            key = _job_key(title, index)
            # Task 6: skip cards already marked "Applied" (never click them). The
            # status text is read from the card itself; a card with no readable
            # status is treated as unapplied and left to the Easy Apply check.
            if skip_applied_card(
                label,
                index=index,
                title=title,
                key=key,
                settings=settings,
                outcome=outcome,
                applied_seen=applied_seen,
                notify=notify,
            ):
                continue
            if key in tried:
                continue
            candidate = (index, card, title, key)
            break

        if candidate is None:
            break

        index, card, title, key = candidate
        tried.add(key)
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
        # Task 3: read the description now, while the job view is intact. On the
        # newer AI/semantic job view the Easy Apply form is rendered inline and can
        # replace the page, hiding the description, so it is read *before* the click.
        if capture is not None and (
            outcome.job_description is None or not outcome.job_description.is_read
        ):
            try:
                outcome.job_description = await capture(page)
            except Exception:  # noqa: BLE001 - best effort; Task 3 re-reads if empty
                outcome.job_description = None
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
            scan.opened = True
            break
        outcome.notes = "Easy Apply form did not open after the click"

    scan.applied_skipped = outcome.applied_jobs_skipped - before_applied
    return scan


async def _task2_on_page(
    page, settings: Settings, notify, skip_keys: set[str] | None = None, capture=None
) -> Task2Outcome:
    """Run Task 2 steps on the results page left open by Task 1.

    Task 6 skips the cards already marked **Applied** and opens the first
    unapplied job. **Task 7:** when *every* card on a page is Applied the results
    list is advanced to the next page (up to ``_MAX_RESULT_PAGES``) and the scan
    runs again there, until an unapplied job is found or there are no more pages.
    Paginating never opens or applies to a job by itself.

    ``skip_keys`` are job keys (see :func:`_job_key`) to ignore — Task 8 uses this
    to never re-open the job the human just submitted, even if its card has not yet
    flipped to **"Applied"**.

    ``capture`` is an optional ``async (page) -> JobDescription`` used by Task 3 to
    read the open job's description while its view is intact (before Easy Apply).
    The result is stored on ``Task2Outcome.job_description``.
    """
    outcome = Task2Outcome()
    tried: set[str] = set(skip_keys or ())
    applied_seen: set[str] = set()
    pages_visited = 0
    exhausted = False

    for page_index in range(_MAX_RESULT_PAGES):
        pages_visited += 1
        scan = await _scan_page(page, settings, notify, outcome, tried, applied_seen, capture)
        outcome.jobs_seen = scan.cards_seen or await results_count(page)
        notify(f"Task 2: {outcome.jobs_seen} job(s) in the list.")
        await _pace(settings)
        if scan.opened:
            break
        # Task 7: only paginate when the whole page was Applied. Otherwise this
        # page has nothing to offer and advancing would not help.
        if scan.cards_seen == 0 or scan.applied_skipped < scan.cards_seen:
            break
        if page_index == _MAX_RESULT_PAGES - 1:
            outcome.notes = _append_note(
                outcome.notes,
                f"reached the results-page cap ({_MAX_RESULT_PAGES}) "
                "while every page was Applied",
            )
            break
        if not await go_to_next_page(page, settings, notify):
            exhausted = True
            break

    outcome.pages_visited = pages_visited
    outcome.page_url = await _safe(page.get_url(), None)
    outcome.page_title = await _safe(page.get_title(), "") or ""

    if not outcome.easy_apply_clicked:
        # Task 6: when every card on this page was skipped as Applied, stop
        # gracefully with a clear note instead of opening (and applying to) one.
        note = applied_skip_note(outcome)
        if note:
            outcome.notes = _append_note(outcome.notes, note)
        if exhausted and pages_visited > 1:
            outcome.notes = _append_note(
                outcome.notes,
                f"searched {pages_visited} results page(s); every job is Applied",
            )
    return outcome


def _task2_ok(outcome: Task2Outcome) -> bool:
    return bool(outcome.easy_apply_clicked and outcome.application_form_opened)
