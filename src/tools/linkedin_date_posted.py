"""Task 13: select LinkedIn's **Date posted** filter ("Past 24 hours").

The classic jobs results page exposes a **Date posted** pill. Clicking it opens
a popover with the range radios (**Past month**, **Past week**, **Past 24
hours**) and a **Show results** button. This module owns that interaction:

* runtime discovery of the pill and the options (never a fixed index/class),
* clicking **Past 24 hours** and applying it with **Show results** when present,
* verifying the selection from the checked option and/or LinkedIn's
  ``f_TPR=r86400`` URL parameter (the canonical **Past 24 hours** range),
* a deterministic URL fallback (preserving the existing query parameters) when
  a layout does not expose the dropdown.

The pure label/range/URL helpers are unit tested directly. The browser steps
reuse Task 1's CDP/marker pattern; nothing is submitted.
"""

from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.configuration import Settings
from src.tools.browser import (
    _loads,
    _marker_element,
    _pace,
    _safe,
    _wait_for_load,
)

# LinkedIn's f_TPR values. Only r86400 satisfies Task 13.
_DATE_RANGE_SECONDS = {
    "past 24 hours": 86400,
    "past week": 604800,
    "past month": 2592000,
}
PAST_24_HOURS_LABEL = "Past 24 hours"
PAST_24_HOURS_VALUE = "past_24_hours"
PAST_24_HOURS_TPR = "r86400"

# How long to wait for the popover's options to render after clicking the pill.
_DATE_OPTION_TIMEOUT_SECONDS = 5.0
_DATE_OPTION_POLL_SECONDS = 0.25


def normalize_label(text: str) -> str:
    """Collapse whitespace, lowercase, and drop a trailing period."""
    return re.sub(r"\s+", " ", (text or "").strip().lower()).rstrip(".")


def _range_key(text: str) -> str:
    """Normalized range/filter label without a trailing "filter" suffix."""
    return re.sub(r"\s+filter$", "", normalize_label(text))


def looks_like_date_range(text: str) -> bool:
    """True for the popover's range labels (Past 24 hours/week/month)."""
    return _range_key(text) in _DATE_RANGE_SECONDS


def looks_like_past_24_hours(text: str) -> bool:
    """True when ``text`` is the **Past 24 hours** option."""
    return _range_key(text) == PAST_24_HOURS_LABEL.lower()


def date_range_seconds(text: str) -> int | None:
    """The range's duration in seconds; ``None`` when the label is not a range."""
    return _DATE_RANGE_SECONDS.get(_range_key(text))


def looks_like_date_posted_filter(text: str) -> bool:
    """True when ``text`` labels the results-page **Date posted** filter.

    Accepts the generic pill label ("Date posted" / "Date posted filter.") and
    the selected-range label LinkedIn may show instead ("Past 24 hours"). It
    deliberately requires the phrase **date posted** (or an exact range label),
    so a job card's "Posted 1 day ago" is never matched.
    """
    normalized = _range_key(text)
    return normalized == "date posted" or normalized in _DATE_RANGE_SECONDS


def pick_past_24_hours_index(labels: list[str]) -> int | None:
    """Return the index of the **Past 24 hours** label, if any."""
    for index, label in enumerate(labels):
        if looks_like_past_24_hours(label):
            return index
    return None


def pick_date_posted_filter_index(labels: list[str]) -> int | None:
    """Return the index of the **Date posted** filter label, if any."""
    for index, label in enumerate(labels):
        if looks_like_date_posted_filter(label):
            return index
    return None


def _query_pairs(url: str) -> tuple[object | None, list[tuple[str, str]]]:
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return None, []
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None, []
    return parts, parse_qsl(parts.query, keep_blank_values=True)


def url_has_past_24_hours(url: str) -> bool:
    """True when the URL carries LinkedIn's ``f_TPR=r86400`` range."""
    _parts, query = _query_pairs(url)
    return any(
        key.lower() == "f_tpr" and value.strip().lower() == PAST_24_HOURS_TPR
        for key, value in query
    )


def with_past_24_hours(url: str) -> str:
    """Return ``url`` with ``f_TPR=r86400``, preserving every other parameter.

    Returns ``""`` for a URL that cannot be parsed, so the caller stops instead
    of navigating somewhere unexpected.
    """
    parts, query = _query_pairs(url)
    if parts is None:
        return ""
    query = [(key, value) for key, value in query if key.lower() != "f_tpr"]
    query.append(("f_TPR", PAST_24_HOURS_TPR))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


# Locate the "Date posted" pill. Scan visible interactive controls and return
# their best accessible label; the pure predicate picks the filter in Python.
_DATE_FILTER_QUERY = r"""
() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-autojob-date]').forEach(
    (el) => el.removeAttribute('data-autojob-date')
  );
  const controls = document.querySelectorAll(
    'button, a, [role="button"], [role="radio"], [role="combobox"], '
    + 'input[type="button"], input[type="submit"]'
  );
  const out = [];
  let i = 0;
  controls.forEach((el) => {
    if (!el.getClientRects().length) return; // skip hidden controls
    const label = norm(
      el.getAttribute('aria-label') || el.innerText
      || el.getAttribute('title') || el.value || ''
    );
    if (!label) return;
    const marker = 'd' + (i++);
    el.setAttribute('data-autojob-date', marker);
    out.push({
      marker: marker,
      label: label,
      checked: el.getAttribute('aria-checked') === 'true'
        || el.getAttribute('aria-pressed') === 'true'
        || el.checked === true
    });
  });
  return JSON.stringify({ controls: out });
}
"""

# Locate the open popover's range options. Radio inputs are preferred (their
# associated <label> is the click target); role=radio/menuitemradio and plain
# labels cover variants without a native input. The filter pill itself is never
# returned: it carries data-autojob-date from the finder above.
_DATE_OPTIONS_QUERY = r"""
() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const ranges = ['past 24 hours', 'past week', 'past month'];
  const isRange = (label) => {
    const text = norm(label).replace(/\.$/, '').replace(/\s+filter$/i, '').toLowerCase();
    return ranges.indexOf(text) !== -1;
  };
  document.querySelectorAll('[data-autojob-date-option]').forEach(
    (el) => el.removeAttribute('data-autojob-date-option')
  );
  const out = [];
  const seen = new Set();
  const add = (el, label, checked, value) => {
    if (!el || seen.has(el)) return;
    if (el.hasAttribute('data-autojob-date')) return; // never the filter pill
    if (!el.getClientRects().length) return;          // skip hidden options
    const text = norm(label);
    if (!isRange(text)) return;
    seen.add(el);
    const marker = 'o' + out.length;
    el.setAttribute('data-autojob-date-option', marker);
    out.push({
      marker: marker,
      label: text,
      checked: checked === true,
      value: value || ''
    });
  };
  document.querySelectorAll('input[type="radio"]').forEach((input) => {
    let label = norm(input.getAttribute('aria-label')) || norm(input.value);
    let labelled = null;
    if (input.id && typeof CSS !== 'undefined' && CSS.escape) {
      labelled = document.querySelector('label[for="' + CSS.escape(input.id) + '"]');
      if (labelled) label = norm(labelled.innerText) || label;
    }
    const checked = input.checked === true || input.getAttribute('aria-checked') === 'true';
    if (isRange(label)) add(labelled || input, label, checked, input.value || '');
  });
  document.querySelectorAll('[role="radio"], [role="menuitemradio"], label, button')
    .forEach((el) => {
      const label = norm(el.getAttribute('aria-label') || el.innerText || '');
      const checked = el.getAttribute('aria-checked') === 'true'
        || el.getAttribute('aria-pressed') === 'true'
        || !!(el.querySelector && el.querySelector('input[type="radio"]:checked'));
      add(el, label, checked, '');
    });
  return JSON.stringify({ options: out });
}
"""

# The popover's apply control. Exact normalized label so a job card's text or a
# "Show more" control is never clicked.
_SHOW_RESULTS_QUERY = r"""
() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase()
    .replace(/\.$/, '');
  document.querySelectorAll('[data-autojob-date-apply]').forEach(
    (el) => el.removeAttribute('data-autojob-date-apply')
  );
  const controls = document.querySelectorAll(
    'button, [role="button"], input[type="button"], input[type="submit"]'
  );
  for (const el of controls) {
    if (!el.getClientRects().length) continue;
    const label = norm(el.getAttribute('aria-label') || el.innerText || el.value || '');
    if (label !== 'show results' && label !== 'apply filter') continue;
    el.setAttribute('data-autojob-date-apply', 'apply');
    return JSON.stringify({ marker: 'apply' });
  }
  return JSON.stringify({ marker: null });
}
"""


async def _settle_after_click(page, settings: Settings) -> None:
    """Wait for a filter click to render/navigate before the next control."""
    if settings.session.post_click_wait_seconds:
        await asyncio.sleep(settings.session.post_click_wait_seconds)
    await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)


async def read_date_controls(page) -> list[dict]:
    """Visible interactive controls with their labels and checked state."""
    payload = _loads(await _safe(page.evaluate(_DATE_FILTER_QUERY), ""))
    controls = payload.get("controls") or []
    return list(controls) if isinstance(controls, list) else []


async def read_date_options(page) -> list[dict]:
    """The open popover's range options, as ``{marker, label, checked, value}``."""
    payload = _loads(await _safe(page.evaluate(_DATE_OPTIONS_QUERY), ""))
    options = payload.get("options") or []
    return list(options) if isinstance(options, list) else []


async def find_date_posted_filter(page):
    """Return the results-page **Date posted** control, or ``None``."""
    controls = await read_date_controls(page)
    index = pick_date_posted_filter_index([c.get("label", "") for c in controls])
    if index is None:
        return None
    marker = controls[index].get("marker")
    return await _marker_element(page, "data-autojob-date", marker) if marker else None


async def find_show_results_button(page):
    """Return the open popover's **Show results** button, or ``None``."""
    payload = _loads(await _safe(page.evaluate(_SHOW_RESULTS_QUERY), ""))
    marker = payload.get("marker")
    return await _marker_element(page, "data-autojob-date-apply", marker) if marker else None


async def wait_for_past_24_hours_option(
    page,
    timeout_seconds: float | None = None,
    poll_seconds: float | None = None,
):
    """Wait for the popover to render and return its **Past 24 hours** option."""
    timeout = _DATE_OPTION_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    poll = _DATE_OPTION_POLL_SECONDS if poll_seconds is None else poll_seconds
    deadline = time.monotonic() + max(timeout, 0)
    while True:
        options = await read_date_options(page)
        index = pick_past_24_hours_index([o.get("label", "") for o in options])
        if index is not None:
            marker = options[index].get("marker")
            if marker:
                return await _marker_element(page, "data-autojob-date-option", marker)
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(poll)


async def date_posted_filter_selected(page) -> bool:
    """True when **Past 24 hours** is applied (URL param or checked option)."""
    current = await _safe(page.get_url(), "") or ""
    if url_has_past_24_hours(current):
        return True
    options = await read_date_options(page)
    return any(
        looks_like_past_24_hours(option.get("label", "")) and option.get("checked")
        for option in options
    )


async def date_posted_filter_applied(page) -> bool:
    """True only when the results URL carries ``f_TPR=r86400``.

    The URL is the authoritative signal that the range was applied to the
    results. A checked radio alone can be a false positive: the popover may be
    open with the option selected but **Show results** not yet applied.
    """
    return url_has_past_24_hours(await _safe(page.get_url(), "") or "")


async def _click(element) -> str:
    """CDP-click a control; return an error note (a navigating click may raise)."""
    try:
        await element.click()
    except Exception as exc:  # noqa: BLE001 - success is judged by verification
        return str(exc)
    return ""


async def select_past_24_hours(page, settings: Settings) -> tuple[bool, str]:
    """Select **Date posted → Past 24 hours**; return ``(selected, note)``.

    Uses the visible UI path (pill → option → **Show results**) and verifies the
    result from the applied ``f_TPR=r86400`` URL. A checked option alone is not
    enough: the popover may not have been applied to the results. When the
    layout has no usable dropdown, it falls back to adding ``f_TPR=r86400`` to
    the current URL while preserving every existing parameter. The caller
    re-checks the Easy Apply filter afterwards because the reload can reset it.
    """
    if await date_posted_filter_applied(page):
        return True, ""

    notes: list[str] = []
    button = await find_date_posted_filter(page)
    if button is None:
        notes.append("Date posted filter control was not found")
    else:
        await _safe(button.evaluate("() => this.scrollIntoView({block: 'center'})"))
        await _pace(settings)
        await _click(button)
        await _settle_after_click(page, settings)

        option = await wait_for_past_24_hours_option(page)
        if option is None:
            # A swallowed click or a hashed popover can leave the list closed;
            # retry the pill's own DOM click once before falling back to the URL.
            await _safe(button.evaluate("() => { this.click(); return true; }"), False)
            await _settle_after_click(page, settings)
            option = await wait_for_past_24_hours_option(page)

        if option is None:
            notes.append("the 'Past 24 hours' option was not found")
        else:
            await _safe(option.evaluate("() => this.scrollIntoView({block: 'center'})"))
            await _pace(settings)
            await _click(option)
            await _settle_after_click(page, settings)

            apply_button = await find_show_results_button(page)
            if apply_button is not None:
                await _safe(apply_button.evaluate("() => this.scrollIntoView({block: 'center'})"))
                await _pace(settings)
                await _click(apply_button)
                await _settle_after_click(page, settings)

            if await date_posted_filter_applied(page):
                return True, "; ".join(notes)
            notes.append("the option was selected but the results URL was not filtered")

    # Deterministic fallback: add f_TPR=r86400 while preserving keywords,
    # f_AL=true, and every other parameter. Only reached when the visible path
    # could not be verified.
    current = await _safe(page.get_url(), "") or ""
    target = with_past_24_hours(current)
    if target:
        await _safe(page.goto(target), None)
        await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)
        if await date_posted_filter_applied(page):
            notes.append("date filter applied via URL fallback (f_TPR=r86400)")
            return True, "; ".join(notes)

    notes.append("'Past 24 hours' could not be verified on the results page")
    return False, "; ".join(notes)


__all__ = [
    "PAST_24_HOURS_LABEL", "PAST_24_HOURS_TPR", "PAST_24_HOURS_VALUE",
    "date_posted_filter_applied", "date_posted_filter_selected", "date_range_seconds",
    "find_date_posted_filter", "find_show_results_button", "looks_like_date_posted_filter",
    "looks_like_date_range", "looks_like_past_24_hours", "normalize_label",
    "pick_date_posted_filter_index", "pick_past_24_hours_index", "read_date_controls",
    "read_date_options", "select_past_24_hours", "url_has_past_24_hours",
    "wait_for_past_24_hours_option", "with_past_24_hours",
]
