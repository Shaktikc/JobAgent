"""Task 7: move to the next results page when the current one has no usable job.

Task 6 skips Applied cards and opens the first unapplied job. When a page yields
no openable Easy Apply job, this module advances to the next page (discovered at
runtime) and lets the scan repeat. It never opens or applies to a job.
"""

from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.configuration import Settings
from src.tools.browser import (
    _first_element,
    _loads,
    _mark_ai_job_cards,
    _pace,
    _safe,
)
from src.tools.linkedin_status_overlay import emit_step

# Safety cap and bounded wait/poll for the next-page check.
_MAX_RESULT_PAGES = 10
_PAGE_WAIT_SECONDS = 20.0
_PAGE_POLL_SECONDS = 0.5
# LinkedIn server-pages results by ``start`` in steps of 25.
_RESULTS_PAGE_SIZE = 25


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def page_number(label: str) -> int | None:
    """The page number in ``"3"`` / ``"Page 3"``; ``None`` for ``"Next"``."""
    match = re.search(r"\d+", label or "")
    return int(match.group()) if match else None


def is_next_label(label: str) -> bool:
    """True for the pagination **Next** control (and not **Previous**)."""
    return "next" in _normalize(label)


def next_page_url(url: str, page_size: int = _RESULTS_PAGE_SIZE) -> str:
    """Advance the results URL's ``start`` by ``page_size``; ``""`` if invalid."""
    if not (url or "").strip():
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    query = parse_qsl(parts.query, keep_blank_values=True)
    current = 0
    for key, value in query:
        if key.lower() == "start":
            try:
                current = int(value)
            except (TypeError, ValueError):
                current = 0
    query = [(key, value) for key, value in query if key.lower() != "start"]
    query.append(("start", str(current + page_size)))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def current_page_number(controls: list[dict]) -> int | None:
    """The page number of the control marked current/active, if one is exposed."""
    for control in controls:
        if control.get("current"):
            return page_number(control.get("label", ""))
    return None


def _pager_scope(controls: list[dict]) -> list[dict]:
    """Keep only controls tagged as the pager; fall back to all when untagged."""
    if not any("pager" in control for control in controls):
        return controls
    scoped = [control for control in controls if control.get("pager")]
    return scoped or controls


def pick_next_page_control(controls: list[dict], current_page: int | None) -> dict | None:
    """Return the next-page control, preferring an enabled **Next** button."""
    controls = _pager_scope(controls)
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
      || (el.getAttribute('aria-current') || '').toLowerCase() === 'page'
      || (el.getAttribute('aria-current') || '').toLowerCase() === 'true';
    controls.push({
      el: el,
      label: label,
      disabled: disabled,
      current: current,
      href: el.getAttribute('href') || ''
    });
  };
  containers.forEach((container) => {
    container.querySelectorAll('button, a, [role="button"]').forEach(add);
  });
  document.querySelectorAll(
    'button[aria-label^="Page " i], a[aria-label^="Page " i], '
    + 'button[aria-label="Next" i], button[aria-label="Previous" i]'
  ).forEach(add);
  // The current LinkedIn results page hashes its CSS class names and puts each
  // page number in its own <li> (so a shared-parent group misses Next). Collect
  // page-number controls and add the enabled Next nearest to the last page
  // number in DOM order. This avoids unrelated "Next" buttons elsewhere.
  const all = Array.from(document.querySelectorAll('button, a, [role="button"]'));
  const order = new Map(all.map((el, index) => [el, index]));
  const pages = [];
  const nexts = [];
  all.forEach((el) => {
    const label = norm(el.getAttribute('aria-label')) || norm(el.innerText);
    if (/^page \d+$/i.test(label)) pages.push(el);
    else if (/^next$/i.test(label)) nexts.push(el);
  });
  let group = null;
  if (pages.length && nexts.length) {
    const lastPage = Math.max(...pages.map((el) => order.get(el) ?? 0));
    const next = nexts.reduce((best, el) =>
      Math.abs((order.get(el) ?? 0) - lastPage)
        < Math.abs((order.get(best) ?? 0) - lastPage) ? el : best
    );
    pages.forEach(add);
    add(next);
    group = new Set(pages.concat([next]));
  }
  const out = controls.map((control, index) => {
    const marker = 'p' + index;
    control.el.setAttribute('data-autojob-page', marker);
    const entry = {
      marker: marker,
      label: control.label,
      disabled: control.disabled,
      current: control.current,
      href: control.href
    };
    // Once the pager group is known, tag every control so a *stray* "Next"
    // elsewhere (for example a details-pane media carousel arrow) is reported
    // pager=false and never clicked as pagination (BUG-069). When no group is
    // found the key is omitted, preserving the original behaviour.
    if (group) {
      entry.pager = group.has(control.el);
    }
    return entry;
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
    last: texts[texts.length - 1] || '',
    url: location.href
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
        "url": payload.get("url") or "",
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


async def _click_control_cdp(element) -> None:
    """CDP-click a resolved control, tolerating a click that starts a navigation.

    ``Element.click()`` dispatches a CDP mouse event at the control's viewport
    coordinates. A click that begins a page navigation can raise *after* the
    navigation has started (the CDP execution context is torn down), which is not
    a failed click — success is judged from whether the results list changed. The
    same reasoning used by ``linkedin_search.click_ai_job_search``.
    """
    try:
        await element.click()
    except Exception:  # noqa: BLE001 - a navigating click tears the CDP context down
        pass


async def _click_control_dom(page, marker: str) -> bool:
    """Dispatch the control's own DOM ``click()`` (last-resort fallback).

    The current LinkedIn results page hashes its class names and renders the
    next-page control as a plain ``<button>`` at the bottom of the page. A CDP
    mouse click at its viewport coordinates can be swallowed by an overlapping
    element (a sticky bar/ad) or by stale geometry, leaving the list unchanged
    even though the control is correct (BUG-068). Calling the DOM node's own
    ``click()`` invokes LinkedIn's handler directly and bypasses hit-testing. Only
    the discovered next-page control is ever clicked this way — never a job card
    and never **Submit application**.
    """
    element = await _first_element(page, [f'[data-autojob-page="{marker}"]'])
    if element is None:
        return False
    clicked = await _safe(
        element.evaluate(
            "() => { this.scrollIntoView({block: 'center'}); this.click(); return true; }"
        ),
        False,
    )
    return bool(clicked)


async def go_to_next_page(
    page,
    settings: Settings,
    notify=None,
    reason_out: list[str] | None = None,
) -> bool:
    """Click the pagination **Next** control and wait for the new page.

    Returns ``True`` once the results list changed (the next page loaded), and
    ``False`` — leaving the list untouched — when the controls cannot be found,
    there is no next page, the control disappears, or the list does not change
    after the click. This only advances the list: it never opens or applies to a
    job.

    ``reason_out`` receives a short technical reason when a *recoverable*
    pagination failure occurs (the controls were not found or the click did not
    move the list). "no next results page" is a genuine clean end, so it is not
    added: Task 8 uses this to decide whether self-healing should retry.
    """
    notify = notify or (lambda _message: None)

    def fail(reason: str) -> bool:
        notify(f"Task 7: {reason}; stopping.")
        if reason_out is not None and "no next results page" not in reason:
            reason_out.append(f"results pagination could not advance: {reason}")
        return False

    info = await read_pagination(page)
    if not info["found"]:
        return fail("pagination controls not found")

    control = pick_next_page_control(info["controls"], info["current"])
    if control is None:
        return fail("no next results page")

    before = await _results_signature(page)
    element = await _first_element(page, [f'[data-autojob-page="{control["marker"]}"]'])
    if element is None:
        return fail("the next-page control disappeared before it could be clicked")

    await _safe(element.evaluate("() => this.scrollIntoView({block: 'center'})"))
    await _pace(settings)
    await _click_control_cdp(element)

    notify(f"Task 7: moving to the next results page (clicked {control['label']!r}).")
    emit_step(notify, "Please wait - moving to the next results page...")
    if await _wait_for_page_change(page, before, settings):
        return True
    # The CDP mouse click did not move the list. On the hashed results page an
    # overlay (a sticky bar/ad) or stale geometry can swallow it, so retry with the
    # control's own DOM click, which invokes LinkedIn's handler directly (BUG-068).
    # Wait again even if the marker is already gone: a *slow* first click may have
    # navigated, in which case the second wait still sees the changed list.
    notify("Task 7: the results did not change; retrying the control directly.")
    await _click_control_dom(page, control["marker"])
    if await _wait_for_page_change(page, before, settings):
        return True
    # Both in-page clicks failed. Load the next results page directly: the list is
    # server-paged by a ``start`` parameter, so a full navigation advances it even
    # when every click is swallowed, the handle went stale, or the clicked control
    # was an unrelated "Next" (BUG-069). This only loads the next page of results;
    # it never opens or applies to a job.
    if await _navigate_to_next_page(page, before, settings, notify):
        return True
    return fail("the results did not change after clicking next")


async def _navigate_to_next_page(page, before: dict, settings: Settings, notify) -> bool:
    """Load the next results page by URL; return ``True`` once the list changed.

    A deterministic fallback for when clicking the pagination control does not
    move the list (an overlay, a stale handle, or a mis-identified **Next**). Only
    runs when the current URL is HTTP(S) and a next page can be built; a URL that
    cannot be advanced returns ``False`` so the caller stops gracefully.
    """
    get_url = getattr(page, "get_url", None)
    current_url = await _safe(get_url(), "") if callable(get_url) else ""
    target = next_page_url(current_url or "")
    if not target:
        return False
    goto = getattr(page, "goto", None)
    if not callable(goto):
        return False
    notify("Task 7: loading the next results page directly.")
    emit_step(notify, "Please wait - loading the next results page...")
    await _safe(goto(target), None)
    return await _wait_for_page_change(page, before, settings)


__all__ = [
    "_MAX_RESULT_PAGES",
    "current_page_number",
    "go_to_next_page",
    "is_next_label",
    "next_page_url",
    "page_number",
    "pick_next_page_control",
    "read_pagination",
]
