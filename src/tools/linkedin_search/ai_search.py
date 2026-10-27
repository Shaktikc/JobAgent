"""Task 1's optional "Try AI job search" detour.

Runtime-scans the page for LinkedIn's AI job search entry point, clicks it, and
repeats the configured query (a capped number of times) while staying in AI
mode. The low-level CDP primitives come from :mod:`src.tools.browser`.
"""

from __future__ import annotations

import asyncio
import time

from src.configuration import Settings
from src.state import Task1Outcome
from src.tools.browser import (
    _APPLY_POLL_SECONDS,
    _append_note,
    _loads,
    _marker_element,
    _pace,
    _safe,
    _wait_for_load,
)
from src.tools.linkedin import pick_ai_job_search_index
from src.tools.linkedin_search.search_box import open_jobs_search
from src.tools.linkedin_status_overlay import emit_step

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

_MAX_AI_JOB_SEARCH_CLICKS = 3


async def _read_ai_candidates(page) -> list[dict]:
    payload = _loads(await _safe(page.evaluate(_AI_CANDIDATES_QUERY), ""))
    return list(payload.get("candidates") or [])


async def find_ai_job_search_button(page):
    """Return LinkedIn's "Try AI job search" control, or ``None`` when absent."""
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
    and the page load is awaited either way so the caller can repeat the search.
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

    The control is optional: when it is absent the search is performed only once.
    When present, each click is followed by a repeat search, retried while the
    control reappears — up to ``_MAX_AI_JOB_SEARCH_CLICKS`` so a persistent
    control can never loop forever. Once clicked the run stays in AI mode and
    never navigates back to the classic jobs search.
    """
    for _ in range(_MAX_AI_JOB_SEARCH_CLICKS):
        ai_button = await wait_for_ai_job_search_button(page, settings)
        if ai_button is None:
            break

        outcome.ai_job_search_present = True
        notify("Task 1: 'Try AI job search' button found; clicking it.")
        emit_step(notify, "Please wait - using LinkedIn's AI job search...")
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
        outcome.ai_job_search_candidates = await read_ai_job_search_candidates(page)
        if outcome.ai_job_search_candidates:
            outcome.notes = _append_note(
                outcome.notes,
                "AI job search not matched; controls seen: "
                + "; ".join(outcome.ai_job_search_candidates[:10]),
            )


__all__ = [
    "_AI_CANDIDATES_QUERY",
    "_MAX_AI_JOB_SEARCH_CLICKS",
    "click_ai_job_search",
    "find_ai_job_search_button",
    "read_ai_job_search_candidates",
    "run_ai_job_search_detour",
    "wait_for_ai_job_search_button",
]
