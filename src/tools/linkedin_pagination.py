"""Task 7: when every job on a results page is "Applied", go to the next page.

Task 6 (:mod:`src.tools.linkedin_skip_applied`) skips the cards already marked
**Applied** and opens the first unapplied job. When *every* card on the current
results page is Applied there is nothing left to open on that page, so this
module advances the results list to the **next page** and lets Task 6's scan run
again on the new page's cards — repeating until an unapplied job is found or
there are no more pages.

The pagination controls are discovered at runtime (LinkedIn renders them as a
page-number list plus **Next** / **Previous** buttons, and the exact markup
varies), so the decision is a pure, unit-testable predicate over the controls'
labels (``pick_next_page_control``) and the browser interaction is kept thin
(``go_to_next_page``). Advancing a page **never** opens or applies to a job: it
only clicks the pagination control and waits for the job list to change.

The caller (:mod:`src.tools.linkedin_job_selection`) owns the job-card scan; this
module only moves between pages and detects when there is no next page.
"""

from __future__ import annotations

import asyncio
import re
import time

from src.configuration import Settings
from src.tools.browser import (
    _first_element,
    _loads,
    _mark_ai_job_cards,
    _pace,
    _safe,
)
from src.tools.linkedin_status_overlay import emit_step

# Safety cap: never advance through more than this many results pages in one run
# while hunting for an unapplied job. A control that never disables can therefore
# never loop forever, consistent with the other click/step caps.
_MAX_RESULT_PAGES = 10

# How long to wait for the new page of cards after clicking Next, and how often
# to poll. Bounded so a click that never changes the list stops instead of hanging.
_PAGE_WAIT_SECONDS = 20.0
_PAGE_POLL_SECONDS = 0.5


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def page_number(label: str) -> int | None:
    """The page number a pagination control's label refers to, or ``None``.

    ``"3"`` and ``"Page 3"`` both return ``3``; ``"Next"`` returns ``None``.
    """
    match = re.search(r"\d+", label or "")
    return int(match.group()) if match else None


def is_next_label(label: str) -> bool:
    """True for the pagination **Next** control (and not **Previous**)."""
    return "next" in _normalize(label)


def current_page_number(controls: list[dict]) -> int | None:
    """The page number of the control marked current/active, if one is exposed."""
    for control in controls:
        if control.get("current"):
            return page_number(control.get("label", ""))
    return None


def pick_next_page_control(controls: list[dict], current_page: int | None) -> dict | None:
    """Return the control that moves to the **next** results page, or ``None``.

    Prefers an explicit, enabled **Next** button. Otherwise, when the current
    page number is known, uses the enabled page-number control for
    ``current_page + 1`` (or the smallest enabled number above the current page).
    Returns ``None`` when there is no next page — a disabled/absent **Next**, or
    no page number above the current one — so the caller stops gracefully.
    """
    for control in controls:
        if is_next_label(control.get("label", "")) and not control.get("disabled"):
            return control
    if current_page is None:
        return None
    for control in controls:
        if control.get("disabled"):
            continue
        if page_number(control.get("label", "")) == current_page + 1:
            return control
    higher = [
        control
        for control in controls
        if not control.get("disabled")
        and (number := page_number(control.get("label", ""))) is not None
        and number > current_page
    ]
    if higher:
        return min(higher, key=lambda control: page_number(control.get("label", "")) or 0)
    return None


# Locate the results-list pagination controls and tag each one with
# ``data-autojob-page`` so it can be resolved back to a browser-use Element.
# The container class varies (classic ``jobs-search-results-list__pagination`` vs
# ``artdeco-pagination``), so this queries a union and also falls back to any
# control whose accessible label is "Page N" / "Next" / "Previous".
_PAGINATION_QUERY = r"""
() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-autojob-page]').forEach(
    (el) => el.removeAttribute('data-autojob-page')
  );
  const containers = Array.from(document.querySelectorAll(
    '.jobs-search-results-list__pagination, .artdeco-pagination, '
    + 'nav[aria-label*="pagination" i], [role="navigation"]'
  ));
  const seen = new Set();
  const controls = [];
  const add = (el) => {
    if (!el || seen.has(el)) return;
    seen.add(el);
    const label = norm(el.getAttribute('aria-label')) || norm(el.innerText);
    if (!label) return;
    const cls = (typeof el.className === 'string') ? el.className : '';
    const disabled = el.disabled === true
      || el.getAttribute('aria-disabled') === 'true'
      || el.hasAttribute('disabled');
    const current = /current|active|selected/i.test(cls)
      || el.getAttribute('aria-current') === 'page';
    controls.push({ el: el, label: label, disabled: disabled, current: current });
  };
  containers.forEach((container) => {
    container.querySelectorAll('button, a, [role="button"]').forEach(add);
  });
  document.querySelectorAll(
    'button[aria-label^="Page " i], a[aria-label^="Page " i], '
    + 'button[aria-label="Next" i], button[aria-label="Previous" i]'
  ).forEach(add);
  const out = controls.map((control, index) => {
    const marker = 'p' + index;
    control.el.setAttribute('data-autojob-page', marker);
    return {
      marker: marker,
      label: control.label,
      disabled: control.disabled,
      current: control.current
    };
  });
  return JSON.stringify({ found: out.length > 0, controls: out });
}
"""

# A cheap fingerprint of the results list, used to tell that a page actually
# changed after clicking Next (count + first/last card text).
_RESULTS_SIGNATURE_JS = r"""
() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const cards = document.querySelectorAll(
    'li.jobs-search-results__list-item, li.scaffold-layout__list-item, '
    + 'div.job-card-container, div.jobs-search-results-list__list-item, '
    + 'ul.jobs-search__results-list > li, [data-autojob-card]'
  );
  const texts = Array.from(cards).map((card) => norm(card.innerText).slice(0, 120));
  return JSON.stringify({
    count: cards.length,
    first: texts[0] || '',
    last: texts[texts.length - 1] || ''
  });
}
"""


async def read_pagination(page) -> dict:
    """Read the results pagination controls.

    Returns ``{"found": bool, "controls": [...], "current": int | None}``. Each
    control is ``{"marker", "label", "disabled", "current"}``; ``found`` is false
    when no controls were discovered, so the caller can stop gracefully.
    """
    payload = _loads(await _safe(page.evaluate(_PAGINATION_QUERY), ""))
    controls = payload.get("controls") or []
    if not isinstance(controls, list):
        controls = []
    return {
        "found": bool(payload.get("found") and controls),
        "controls": controls,
        "current": current_page_number(controls),
    }


async def _results_signature(page) -> dict:
    """Fingerprint of the current results list (count + first/last card text)."""
    await _mark_ai_job_cards(page)
    payload = _loads(await _safe(page.evaluate(_RESULTS_SIGNATURE_JS), ""))
    try:
        count = int(payload.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    return {
        "count": count,
        "first": payload.get("first") or "",
        "last": payload.get("last") or "",
    }


async def _wait_for_page_change(page, before: dict, settings: Settings) -> bool:
    """Wait until the results list differs from ``before`` (a new page loaded)."""
    deadline = time.monotonic() + _PAGE_WAIT_SECONDS
    while time.monotonic() < deadline:
        await asyncio.sleep(_PAGE_POLL_SECONDS)
        after = await _results_signature(page)
        if after["count"] and after != before:
            return True
    return False


async def go_to_next_page(page, settings: Settings, notify=None) -> bool:
    """Click the pagination **Next** control and wait for the new page.

    Returns ``True`` once the results list changed (the next page loaded), and
    ``False`` — leaving the list untouched — when the controls cannot be found,
    there is no next page, the control disappears, or the list does not change
    after the click. This only advances the list: it never opens or applies to a
    job.
    """
    notify = notify or (lambda _message: None)
    info = await read_pagination(page)
    if not info["found"]:
        notify("Task 7: pagination controls not found; stopping.")
        return False

    control = pick_next_page_control(info["controls"], info["current"])
    if control is None:
        notify("Task 7: no next results page; stopping.")
        return False

    before = await _results_signature(page)
    element = await _first_element(page, [f'[data-autojob-page="{control["marker"]}"]'])
    if element is None:
        notify("Task 7: the next-page control disappeared before it could be clicked.")
        return False

    await _safe(element.evaluate("() => this.scrollIntoView({block: 'center'})"))
    await _pace(settings)
    try:
        await element.click()
    except Exception as exc:  # noqa: BLE001 - a vanished control is a graceful stop
        notify(f"Task 7: could not click the next-page control ({exc}).")
        return False

    notify(f"Task 7: moving to the next results page (clicked {control['label']!r}).")
    emit_step(notify, "Please wait - moving to the next results page...")
    if await _wait_for_page_change(page, before, settings):
        return True
    notify("Task 7: the results did not change after clicking next; stopping.")
    return False


__all__ = [
    "_MAX_RESULT_PAGES",
    "current_page_number",
    "go_to_next_page",
    "is_next_label",
    "page_number",
    "pick_next_page_control",
    "read_pagination",
]
