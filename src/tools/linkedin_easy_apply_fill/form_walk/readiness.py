"""Wait for dynamically rendered Easy Apply fields and navigation."""

import asyncio
import time

from src.configuration import Settings
from src.tools.forms import looks_like_next, looks_like_submit
from src.tools.linkedin_easy_apply_fill.form_queries import read_form, read_form_buttons


def _step_has_controls(fields: list[dict], buttons: list[dict]) -> bool:
    """True when a read step has rendered something the walk can act on.

    LinkedIn's newer SDUI Easy Apply renders the ``<dialog>`` and its heading
    before the contact fields and navigation footer. Such an empty shell is *not*
    a terminal step: it must be re-read until the step renders. A step is ready
    when it has fillable fields or a navigation/submit button (a dismiss button
    is not navigation).
    """
    if fields:
        return True
    return any(
        looks_like_next(str(button.get("text") or ""))
        or looks_like_submit(str(button.get("text") or ""))
        for button in buttons
    )


async def _step_when_ready(
    page,
    settings: Settings,
    opened: bool,
    title: str,
    fields: list[dict],
    step: str,
) -> tuple[bool, str, list[dict], str, bool, list[dict] | None]:
    """Wait for a just-opened Easy Apply step to finish rendering (BUG-056).

    The modal's heading can appear well before its fields and footer, and an empty
    read used to look like the terminal step (no Next) — so the walk stopped with
    no resume and no fields. Poll for real controls up to the easy-apply timeout
    and report ``ready=False`` when the form never renders them.

    When the step has no fields the buttons read here are returned so the caller
    can reuse them after filling (nothing was filled), instead of reading them a
    second time; a fake/lagging page that advances its button state on every read
    would otherwise look like the step had changed.
    """
    if not opened or fields:
        return opened, title, fields, step, bool(opened), None

    buttons = await read_form_buttons(page)
    if _step_has_controls(fields, buttons):
        return opened, title, fields, step, True, buttons

    deadline = time.monotonic() + settings.session.easy_apply_timeout_seconds
    while time.monotonic() < deadline:
        await asyncio.sleep(min(0.5, max(deadline - time.monotonic(), 0)))
        opened, title, fields, step = await read_form(page)
        if not opened:
            return opened, title, fields, step, False, buttons
        if fields:
            return opened, title, fields, step, True, None
        buttons = await read_form_buttons(page)
        if _step_has_controls(fields, buttons):
            return opened, title, fields, step, True, buttons
    return opened, title, fields, step, False, buttons
