"""Task 1's Easy Apply filter helpers.

The filter is a choice toggle on the results page; its label and markup vary
between LinkedIn layouts. The run finds it by visible/accessible label, prefers
a real choice toggle over a job's blue apply button, and verifies the selection
through ``aria-checked``/``aria-pressed`` or ``f_AL=true`` in the URL.
"""

from __future__ import annotations

from src.configuration import Settings
from src.tools.browser import (
    _element_is_apply_button,
    _element_is_choice_control,
    _element_label,
    _loads,
    _pace,
    _query_elements,
    _safe,
    _wait_for_load,
)
from src.tools.linkedin import (
    looks_like_easy_apply,
    pick_easy_apply_filter_index,
    pick_easy_apply_index,
)
from src.tools.linkedin_search.common import _settle_after_click

# LinkedIn renders the Easy Apply filter toggle with this aria-label; the phrase
# check below is a fallback for markup variants. The exact "Easy Apply" phrase
# is required so an unrelated "Apply" control is never matched.
_EASY_APPLY_FILTER_SELECTORS = (
    "button[aria-label*='Easy Apply']",
    "[role='button'][aria-label*='Easy Apply']",
)

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


async def find_easy_apply_filter(page):
    """Return the Easy Apply *filter* toggle, or ``None`` when absent.

    The results page shows two controls whose accessible name contains "Easy
    Apply": the results filter pill (``id="searchFilter_applyWithLinkedin"``,
    ``role="radio"`` with ``aria-checked``, class ``search-reusables__filter-pill-button``)
    and the blue "Easy Apply" apply button on a job (``jobs-apply-button`` /
    ``artdeco-button--primary``). They share the label text, so they are told
    apart by structure: the filter is a choice toggle
    (``role="radio"``/``aria-checked`` or ``aria-pressed``) and is never a
    ``jobs-apply-button``.

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


async def select_easy_apply_filter(
    page, settings: Settings, *, prefer_url: bool = False
) -> tuple[bool, str]:
    """Click the Easy Apply filter; return ``(selected, note)``.

    ``prefer_url`` applies the filter through the ``f_AL=true`` query parameter
    instead of clicking the pill. Task 1 uses it after the Date posted filter so
    the reload preserves the date range (a pill click can reset it).
    """
    note = ""
    if prefer_url:
        current = await _safe(page.get_url(), "") or ""
        if current:
            separator = "&" if "?" in current else "?"
            target = current if "f_AL=true" in current else f"{current}{separator}f_AL=true"
            await page.goto(target)
            await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)
            if await easy_apply_filter_selected(page):
                return True, note
            return False, "Easy Apply filter could not be selected via the results URL"

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


__all__ = [
    "_EASY_APPLY_FILTER_SELECTORS",
    "_FILTER_QUERY",
    "easy_apply_filter_selected",
    "find_easy_apply_filter",
    "select_easy_apply_filter",
]
