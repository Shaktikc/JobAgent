"""Task 2: select a job from the search results and read its description.

This module owns Task 2's interactive browser flow, split out of
:mod:`src.tools.browser`:

1. Read the job cards currently displayed in the search-results list left open by
   Task 1.
2. Open the first (or next) job that offers **Easy Apply**, skipping jobs already
   marked "Applied" when ``settings.session.skip_applied`` is set, and read its
   description.
3. Leave the form closed in the match-first flow (``open_form=False``); the
   caller opens it only after a resume match (Task 16). Older one-shot callers can
   still click the details pane's **Easy Apply** button and confirm the form.

The details pane itself — which job it shows, its apply button, and the Easy Apply
modal check — lives in :mod:`src.tools.linkedin_job_apply_button`; the card/pane
opening helpers live in :mod:`src.tools.linkedin_job_card`. Both are re-exported
here for back-compat. Before judging the apply button, the walk
verifies that the pane actually switched to the clicked job
(:func:`open_job_card`): a card click that left the pane on the *previous*
(already-applied) job has no Easy Apply control at all, which used to be reported
as "no Easy Apply" and skipped a job that does offer it (BUG-036).

Task 6's applied-job detection (classify a card as **Applied**, record the skip,
and produce the "no unapplied job" note) lives in
:mod:`src.tools.linkedin_skip_applied`; this module calls it while scanning.
Task 7's pagination lives in :mod:`src.tools.linkedin_pagination`: when the
current page yields **no selectable Easy Apply job** (every card Applied, or the
remaining unapplied cards have no Easy Apply), this module advances the results
list to the next page (up to ``_MAX_RESULT_PAGES``) and scans it again.
The interaction uses browser-use's deterministic CDP actor API (``Page`` /
``Element``); no LLM is involved.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from src.configuration import Settings
from src.state import Task2Outcome
from src.tools.browser import (
    _RESULTS_WAIT_SECONDS,
    _append_note,
    _element_label,
    _mark_ai_job_cards,
    _pace,
    _query_elements,
    _safe,
)
from src.tools.linkedin import looks_like_easy_apply_action
from src.tools.linkedin_job_apply_button import (
    _APPLY_MODAL_QUERY,
    _JOB_DETAILS_APPLY_SELECTORS,
    _element_is_job_card,
    find_job_apply_button,
    pane_shows_job,
    read_apply_modal,
    read_details_pane_job,
    wait_for_easy_apply_modal,
    wait_for_job_apply_button,
)

# The card/pane helpers are re-exported here for existing callers.
from src.tools.linkedin_job_card import (
    _first_line,
    _job_key,
    find_card_by_title,
    open_job_card,
)
from src.tools.linkedin_results_scan import scan_results_pages
from src.tools.linkedin_skip_applied import skip_applied_card
from src.tools.linkedin_status_overlay import emit_step

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


async def read_job_cards(page) -> list:
    """Return the job cards currently shown in the search results list."""
    # Ensure AI/semantic job cards are marked so [data-autojob-card] resolves them.
    await _mark_ai_job_cards(page)
    for selector in _JOB_CARD_SELECTORS:
        cards = await _query_elements(page, selector)
        if cards:
            return cards
    return []


@dataclass
class _PageScan:
    """What one pass over a single results page produced (Tasks 2 and 6)."""

    opened: bool = False
    selected: bool = False
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
    open_form: bool = True,
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
        emit_step(notify, f"Please wait - opening job {index + 1}: {title or '(untitled)'}...")
        opened, pane_title = await open_job_card(page, card, title, settings, notify)
        if not opened:
            # The pane never showed this job, so its apply button says nothing
            # about the job we asked for: report *that* (a stale card click)
            # instead of the misleading "no Easy Apply".
            outcome.skipped_jobs += 1
            other = pane_title or "(an unknown job)"
            outcome.notes = _append_note(
                outcome.notes, f"the details pane still shows {other} for job {index + 1}"
            )
            head = f"Task 2: the details pane did not open job {index + 1}"
            notify(f"{head}: {title or '(untitled)'}; skipping.")
            emit_step(notify, f"Skipping job {index + 1} - the job details did not open.")
            continue

        button, label = await wait_for_job_apply_button(page, settings)
        if button is None or not looks_like_easy_apply_action(label):
            outcome.skipped_jobs += 1
            notify("Task 2: no Easy Apply for this job; skipping.")
            emit_step(notify, f"Skipping job {index + 1} - no Easy Apply.")
            continue

        outcome.easy_apply_button_found = True
        outcome.job_selected = True
        # Task 3: read the description now, while the job view is intact. On the
        # newer AI/semantic job view the Easy Apply form is rendered inline and can
        # replace the page, hiding the description, so it is read *before* the click.
        if capture is not None and (
            outcome.job_description is None or not outcome.job_description.is_read
        ):
            emit_step(notify, "Please wait - reading the job description...")
            try:
                outcome.job_description = await capture(page)
            except Exception:  # noqa: BLE001 - best effort; Task 3 re-reads if empty
                outcome.job_description = None
        # Task 16: in the match-first flow, stop here. The job and its Easy Apply
        # button are selected, and the description is read, but the form stays
        # closed until the resume matcher decides the job is worth applying to.
        if not open_form:
            outcome.job_selected = True
            scan.selected = True
            notify(
                f"Task 2: selected job {index + 1}: {title or '(untitled)'}; "
                "waiting for the resume match before Easy Apply."
            )
            emit_step(
                notify,
                f"Selected {title or 'this job'} - checking for a matching resume...",
            )
            break

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
            emit_step(notify, f"Opened the Easy Apply form for {title or 'this job'}.")
            scan.opened = True
            break
        outcome.notes = "Easy Apply form did not open after the click"

    scan.applied_skipped = outcome.applied_jobs_skipped - before_applied
    return scan


async def _task2_on_page(
    page,
    settings: Settings,
    notify,
    skip_keys: set[str] | None = None,
    capture=None,
    open_form: bool = True,
    date_range: str = "",
    preferred_range: str = "",
) -> Task2Outcome:
    """Run Task 2 steps on the results page left open by Task 1.

    Task 6 skips the cards already marked **Applied** and opens the first
    unapplied job. **Task 7** advances the results list while a page yields no
    openable Easy Apply job. **Task 17** then falls back from the range chosen at
    startup to the other range (Past 24 hours ⇄ Past week, page 1) and keeps
    scanning; a list already on the fallback range stays on it. Paginating and
    switching the range never open or apply to a job by themselves.

    ``skip_keys`` are job keys (see :func:`_job_key`) to ignore — Task 8 uses this
    to never re-open the job the human just submitted, even if its card has not yet
    flipped to **"Applied"**.

    ``capture`` is an optional ``async (page) -> JobDescription`` used by Task 3 to
    read the open job's description while its view is intact (before Easy Apply).
    The result is stored on ``Task2Outcome.job_description``.

    ``open_form=False`` is Task 16's match-first flow: select the first job that
    offers Easy Apply and read its description, but leave the form closed. The
    caller opens it only after a resume match (``open_form`` node).

    ``date_range`` is the range the caller knows the current list uses (Task 8
    passes the previous scan's ``date_range_used``). When empty, the range is
    detected from the results URL/a checked Date posted option.

    ``preferred_range`` is the range the user chose at startup. It makes the
    fallback direction correct (24 hours ⇄ past week) and prevents a later pass
    that is already on the fallback range from scanning both ranges again.
    """
    outcome = Task2Outcome()
    emit_step(notify, "Please wait - reading the job results list...")
    scan_kwargs: dict = {
        "capture": capture,
        "open_form": open_form,
        "date_range": date_range,
    }
    if preferred_range:
        scan_kwargs["preferred_range"] = preferred_range
    await scan_results_pages(
        page,
        settings,
        notify,
        outcome,
        set(skip_keys or ()),
        set(),
        _scan_page,
        **scan_kwargs,
    )
    outcome.page_url = await _safe(page.get_url(), None)
    outcome.page_title = await _safe(page.get_title(), "") or ""
    return outcome


def _task2_ok(outcome: Task2Outcome) -> bool:
    return bool(outcome.easy_apply_clicked and outcome.application_form_opened)


def _task2_selected_ok(outcome: Task2Outcome) -> bool:
    """True when Task 2 selected a job that offers Easy Apply (form optional)."""
    return bool(outcome.job_selected and outcome.easy_apply_button_found)


# Task 2's public API. The details-pane names are re-exported from
# :mod:`src.tools.linkedin_job_apply_button` (they are imported above), so
# ``from src.tools.linkedin_job_selection import ...`` and the lazy re-exports in
# :mod:`src.tools.browser` keep working unchanged.
__all__ = [
    "_APPLY_MODAL_QUERY",
    "_JOB_CARD_SELECTORS",
    "_JOB_DETAILS_APPLY_SELECTORS",
    "_MAX_JOB_ATTEMPTS",
    "_element_is_job_card",
    "_first_line",
    "_task2_ok",
    "_task2_on_page",
    "_task2_selected_ok",
    "find_card_by_title",
    "find_job_apply_button",
    "open_job_card",
    "pane_shows_job",
    "read_apply_modal",
    "read_details_pane_job",
    "read_job_cards",
    "wait_for_easy_apply_modal",
    "wait_for_job_apply_button",
]
