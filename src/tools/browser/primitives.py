"""Small CDP helpers shared by search, form filling, and submission."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from datetime import UTC, datetime

from src.configuration import Settings
from src.tools.browser.queries import _AI_JOB_CARDS_JS, _RESULTS_QUERY


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


async def _element_is_choice_control(element) -> bool:
    """True when the control is the results *filter* toggle, not an apply button.

    LinkedIn renders the "Easy Apply" results filter pill as a choice toggle: it
    is ``role="radio"`` carrying ``aria-checked`` (or a plain toggle carrying
    ``aria-pressed``). A job's "Easy Apply" apply button is a plain
    ``artdeco-button`` and has neither. This structural signal — not the label,
    which both controls share — is what tells the two apart on the real page.
    """
    if await _safe(element.get_attribute("aria-checked"), None) is not None:
        return True
    return await _safe(element.get_attribute("aria-pressed"), None) is not None


async def _element_is_apply_button(element) -> bool:
    """True when the control is a job's "Easy Apply" apply button, not the filter.

    LinkedIn marks the blue apply button with the ``jobs-apply-button`` class
    (and a ``data-live-test-job-apply-button`` hook), which the results filter
    pill never carries. This lets the filter finder skip it even when its
    accessible name also contains "Easy Apply".
    """
    css_class = await _safe(element.get_attribute("class"), "") or ""
    if "jobs-apply-button" in css_class:
        return True
    return await _safe(element.get_attribute("data-live-test-job-apply-button"), None) is not None


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


async def results_count(page) -> int:
    """Number of job cards currently rendered on the search results page."""
    payload = _loads(await _safe(page.evaluate(_RESULTS_QUERY), ""))
    try:
        count = int(payload.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count == 0:
        # AI/semantic results page: its job cards are div[role="button"], which
        # the classic selectors in _RESULTS_QUERY cannot see.
        count = await _mark_ai_job_cards(page)
    return count


async def _mark_ai_job_cards(page) -> int:
    """Mark AI/semantic job-card controls and return how many were found.

    LinkedIn's AI job search renders results as ``div[role="button"]`` job cards
    that the classic ``<li>`` selectors miss. This tags each one with
    ``data-autojob-card`` (see :data:`_JOB_CARD_ATTR`) so ``read_job_cards`` can
    resolve them, and returns the count for :func:`results_count`.
    """
    payload = _loads(await _safe(page.evaluate(_AI_JOB_CARDS_JS), ""))
    try:
        return int(payload.get("count") or 0)
    except (TypeError, ValueError):
        return 0


def _append_note(existing: str, extra: str) -> str:
    return f"{existing}; {extra}" if existing else extra


async def _marker_element(page, attribute: str, marker: str):
    return await _first_element(page, [f'[{attribute}="{marker}"]'])


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
