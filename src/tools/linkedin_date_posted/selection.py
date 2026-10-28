"""Task 13/17: deterministic browser steps for LinkedIn's **Date posted** filter.

The classic jobs results page exposes a **Date posted** pill. Clicking it opens
a popover with the range radios (**Past month**, **Past week**, **Past 24
hours**) and a **Show results** button. This module owns the interaction:

* runtime discovery of the pill and the options (never a fixed index/class),
* clicking a range and applying it with **Show results** when present,
* verifying the selection from LinkedIn's ``f_TPR`` URL parameter,
* a deterministic URL fallback (preserving the existing query parameters) when
  a layout does not expose the dropdown,
* resetting the results page offset when switching ranges (Task 17).

Task 13 uses :func:`select_past_24_hours`; Task 17 calls
:func:`select_past_week` (or the generic :func:`select_date_range`). The pure
label/range helpers live in :mod:`src.tools.linkedin_date_posted.labels` and the
URL helpers in :mod:`src.tools.linkedin_date_posted.urls`.
"""

from __future__ import annotations

import asyncio
import time

from src.configuration import Settings
from src.tools.browser import (
    _loads,
    _marker_element,
    _pace,
    _safe,
    _wait_for_load,
)
from src.tools.linkedin_date_posted.labels import (
    PAST_24_HOURS_LABEL,
    PAST_24_HOURS_TPR,
    PAST_WEEK_LABEL,
    PAST_WEEK_TPR,
    date_range_tpr,
    normalize_label,
    pick_date_posted_filter_index,
    pick_date_range_index,
)
from src.tools.linkedin_date_posted.queries import (
    _DATE_FILTER_QUERY,
    _DATE_OPTIONS_QUERY,
    _SHOW_RESULTS_QUERY,
)
from src.tools.linkedin_date_posted.urls import (
    has_page_offset,
    url_has_date_range,
    with_date_range,
)

# How long to wait for the popover's options to render after clicking the pill.
_DATE_OPTION_TIMEOUT_SECONDS = 5.0
_DATE_OPTION_POLL_SECONDS = 0.25


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


async def wait_for_range_option(
    page,
    label: str,
    timeout_seconds: float | None = None,
    poll_seconds: float | None = None,
):
    """Wait for the popover to render and return the option named ``label``."""
    timeout = _DATE_OPTION_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    poll = _DATE_OPTION_POLL_SECONDS if poll_seconds is None else poll_seconds
    deadline = time.monotonic() + max(timeout, 0)
    while True:
        options = await read_date_options(page)
        index = pick_date_range_index([o.get("label", "") for o in options], label)
        if index is not None:
            marker = options[index].get("marker")
            if marker:
                return await _marker_element(page, "data-autojob-date-option", marker)
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(poll)


async def wait_for_past_24_hours_option(
    page,
    timeout_seconds: float | None = None,
    poll_seconds: float | None = None,
):
    """Wait for the popover to render and return its **Past 24 hours** option."""
    return await wait_for_range_option(
        page, PAST_24_HOURS_LABEL, timeout_seconds, poll_seconds
    )


async def wait_for_past_week_option(
    page,
    timeout_seconds: float | None = None,
    poll_seconds: float | None = None,
):
    """Wait for the popover to render and return its **Past week** option."""
    return await wait_for_range_option(page, PAST_WEEK_LABEL, timeout_seconds, poll_seconds)


async def date_range_selected(page, label: str) -> bool:
    """True when ``label`` is applied (URL parameter or checked option)."""
    tpr = date_range_tpr(label)
    if tpr and url_has_date_range(await _safe(page.get_url(), "") or "", tpr):
        return True
    wanted = normalize_label(label)
    options = await read_date_options(page)
    return any(
        normalize_label(option.get("label", "")) == wanted and option.get("checked")
        for option in options
    )


async def date_posted_filter_selected(page) -> bool:
    """True when **Past 24 hours** is applied (URL param or checked option)."""
    return await date_range_selected(page, PAST_24_HOURS_LABEL)


async def date_range_applied(page, tpr: str) -> bool:
    """True only when the results URL carries ``f_TPR=<tpr>``.

    The URL is the authoritative signal that the range was applied to the
    results. A checked radio alone can be a false positive: the popover may be
    open with the option selected but **Show results** not yet applied.
    """
    return url_has_date_range(await _safe(page.get_url(), "") or "", tpr)


async def date_posted_filter_applied(page) -> bool:
    """True only when the results URL carries ``f_TPR=r86400``."""
    return await date_range_applied(page, PAST_24_HOURS_TPR)


async def _click(element) -> str:
    """CDP-click a control; return an error note (a navigating click may raise)."""
    try:
        await element.click()
    except Exception as exc:  # noqa: BLE001 - success is judged by verification
        return str(exc)
    return ""


async def _reset_page_offset(page, settings: Settings, tpr: str, notes: list[str]) -> bool:
    """Reload page 1 of the same range when the URL kept a ``start`` offset."""
    current = await _safe(page.get_url(), "") or ""
    if not has_page_offset(current):
        return True
    target = with_date_range(current, tpr, reset_start=True)
    if not target:
        return True
    await _safe(page.goto(target), None)
    await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)
    if await date_range_applied(page, tpr):
        return True
    notes.append("the results page offset could not be reset")
    return False


async def select_date_range(
    page,
    settings: Settings,
    label: str,
    tpr: str,
    *,
    reset_start: bool = False,
) -> tuple[bool, str]:
    """Select **Date posted → ``label``**; return ``(selected, note)``.

    Uses the visible UI path (pill → option → **Show results**) and verifies the
    result from the applied ``f_TPR`` URL. A checked option alone is not enough:
    the popover may not have been applied to the results. When the layout has no
    usable dropdown, it falls back to adding/replacing ``f_TPR`` in the current
    URL while preserving every existing parameter. ``reset_start`` reloads page 1
    of the new range when the previous range left a pagination offset (Task 17).
    The caller re-checks the Easy Apply filter afterwards because the reload can
    reset it.
    """
    if await date_range_applied(page, tpr):
        if not reset_start:
            return True, ""
        notes: list[str] = []
        if await _reset_page_offset(page, settings, tpr, notes):
            return True, ""
        return False, "; ".join(notes)

    notes: list[str] = []
    button = await find_date_posted_filter(page)
    if button is None:
        notes.append("Date posted filter control was not found")
    else:
        await _safe(button.evaluate("() => this.scrollIntoView({block: 'center'})"))
        await _pace(settings)
        await _click(button)
        await _settle_after_click(page, settings)

        option = await wait_for_range_option(page, label)
        if option is None:
            # A swallowed click or a hashed popover can leave the list closed;
            # retry the pill's own DOM click once before falling back to the URL.
            await _safe(button.evaluate("() => { this.click(); return true; }"), False)
            await _settle_after_click(page, settings)
            option = await wait_for_range_option(page, label)

        if option is None:
            notes.append(f"the {label!r} option was not found")
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

            if await date_range_applied(page, tpr):
                if not reset_start:
                    return True, "; ".join(notes)
                if await _reset_page_offset(page, settings, tpr, notes):
                    return True, "; ".join(notes)
            else:
                notes.append("the option was selected but the results URL was not filtered")

    # Deterministic fallback: add/replace f_TPR while preserving keywords,
    # f_AL=true, and every other parameter. Only reached when the visible path
    # could not be verified.
    current = await _safe(page.get_url(), "") or ""
    target = with_date_range(current, tpr, reset_start=reset_start)
    if target:
        await _safe(page.goto(target), None)
        await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)
        if await date_range_applied(page, tpr):
            notes.append(f"date filter applied via URL fallback (f_TPR={tpr})")
            return True, "; ".join(notes)

    notes.append(f"{label!r} could not be verified on the results page")
    return False, "; ".join(notes)


async def select_past_24_hours(page, settings: Settings) -> tuple[bool, str]:
    """Select **Date posted → Past 24 hours**; return ``(selected, note)``."""
    return await select_date_range(page, settings, PAST_24_HOURS_LABEL, PAST_24_HOURS_TPR)


async def select_past_week(page, settings: Settings) -> tuple[bool, str]:
    """Select **Date posted → Past week** and start at page 1 (Task 17)."""
    return await select_date_range(
        page, settings, PAST_WEEK_LABEL, PAST_WEEK_TPR, reset_start=True
    )


__all__ = [
    "_DATE_OPTION_POLL_SECONDS",
    "_DATE_OPTION_TIMEOUT_SECONDS",
    "date_posted_filter_applied",
    "date_posted_filter_selected",
    "date_range_applied",
    "date_range_selected",
    "find_date_posted_filter",
    "find_show_results_button",
    "read_date_controls",
    "read_date_options",
    "select_date_range",
    "select_past_24_hours",
    "select_past_week",
    "wait_for_past_24_hours_option",
    "wait_for_past_week_option",
    "wait_for_range_option",
]
