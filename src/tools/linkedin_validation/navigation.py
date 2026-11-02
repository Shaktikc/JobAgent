"""Bounded navigation recovery; validation receives one correction and retry."""

import asyncio
import time

from src.tools.browser import _marker_element, _safe
from src.tools.forms import pick_next_button
from src.tools.linkedin_status_overlay import emit_step
from src.tools.linkedin_validation.correction import correct_rejections, failure
from src.tools.linkedin_validation.detection import read_rejections


async def finish_advance(
    page,
    current,
    previous,
    settings,
    notify,
    outcome,
    chooser,
    corrected_steps,
    *,
    read,
    buttons,
    signature_of,
    blur,
):
    """Wait for a step change, correcting validation before any navigation retry.

    Reader callbacks preserve the existing walk's runtime and monkeypatch seams.
    A navigation failure without validation keeps its original single retry.
    """

    def unchanged(snapshot):
        opened, title, fields, step = snapshot
        return opened and signature_of(title, fields, step) == previous

    async def poll(snapshot, *, stop_on_rejection):
        deadline = time.monotonic() + settings.session.easy_apply_timeout_seconds
        while unchanged(snapshot):
            if stop_on_rejection:
                rejected = await read_rejections(page, snapshot[2])
                if rejected:
                    return snapshot, rejected
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(min(0.25, max(deadline - time.monotonic(), 0)))
            snapshot = await read(page)
        return snapshot, []

    async def click_next():
        button = pick_next_button(await buttons(page))
        element = (
            await _marker_element(page, "data-autojob-btn", button["marker"])
            if button is not None
            else None
        )
        if element is None:
            return False
        await blur(page)
        await _safe(element.click())
        if settings.session.post_click_wait_seconds:
            await asyncio.sleep(settings.session.post_click_wait_seconds)
        return True

    generic_retry_used = False
    while unchanged(current):
        current, issues = await poll(current, stop_on_rejection=True)
        if not unchanged(current):
            return current
        if not issues:
            if generic_retry_used:
                return current
            generic_retry_used = True
            notify("Task 4: Next did not advance; retrying once with a fresh button handle.")
            if not await click_next():
                return current
            current = await read(page)
            continue  # The retry may be the first click to trigger field validation.

        attempted, retries = False, 0
        try:
            if corrected_steps.get(previous) is True:
                outcome.validation = failure(
                    issues,
                    True,
                    1,
                    "this step already used its correction retry",
                )
                return current
            if previous in corrected_steps:
                corrected, attempted = True, True  # Repaired before an unrelated human prompt.
            else:
                corrected_steps[previous] = False
                emit_step(notify, "Correcting invalid input before retrying this form step...")
                corrected, attempted = await correct_rejections(
                    page,
                    issues,
                    chooser,
                    outcome,
                    notify,
                )
            if not corrected:
                outcome.validation = failure(
                    issues,
                    attempted,
                    reason=("no truthful valid correction was available for every rejected field"),
                )
                return current
            corrected_steps[previous] = True
            notify("Task 20: retrying the corrected step once.")
            retries = int(await click_next())
            current = await read(page)
            current, _ = await poll(current, stop_on_rejection=False)
            if unchanged(current) or not current[0]:
                remaining = await read_rejections(page, current[2]) if current[0] else []
                outcome.validation = failure(remaining or issues, attempted, retries)
            else:
                emit_step(notify, "Invalid input corrected - continuing this application.")
        except Exception as exc:
            # Keep the original rejection even when a chooser/DOM operation
            # fails; losing it would wrongly relaunch structural self-healing.
            outcome.validation = failure(
                issues,
                attempted,
                retries,
                f"validation correction failed ({type(exc).__name__})",
            )
        return current
    return current
