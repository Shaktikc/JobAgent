"""Task 4: attach the Task 3 resume to the open Easy Apply form.

This module owns the resume attachment, split out of
:mod:`src.tools.linkedin_easy_apply_fill`. The resume control is dynamic, so it
prefers a resume already listed on the current step (a radio option or a
``<select>`` choice); otherwise it uploads the file over CDP, clicking an
"Upload resume" button first when that is what reveals the file input.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.configuration import Settings
from src.state import Task4Outcome
from src.tools.browser import _append_note, _first_element, _marker_element, _safe
from src.tools.forms import pick_listed_resume
from src.tools.linkedin_easy_apply_fill.field_filling import _FILL_SELECT_JS
from src.tools.linkedin_easy_apply_fill.form_queries import read_resume_info
from src.tools.linkedin_status_overlay import emit_step


async def upload_file_via_cdp(session, page, selector: str, file_path: str) -> None:
    """Attach ``file_path`` to the file input matching ``selector`` over CDP.

    Uses the page's own CDP session (``page.session_id``) so the element is
    resolved in the tab we are driving, and ``Runtime.evaluate`` to obtain the
    element's object id for ``DOM.setFileInputFiles``.
    """
    if not Path(file_path).is_file():
        raise RuntimeError(f"resume file does not exist: {file_path}")
    client = session.cdp_client
    session_id = await page.session_id
    await client.send.DOM.enable(session_id=session_id)
    expression = f"document.querySelector({json.dumps(selector)})"
    found = await client.send.Runtime.evaluate(
        params={"expression": expression, "returnByValue": False}, session_id=session_id
    )
    object_id = (found.get("result") or {}).get("objectId")
    if not object_id:
        raise RuntimeError(f"file input not found: {selector}")
    await client.send.DOM.setFileInputFiles(
        params={"files": [file_path], "objectId": object_id}, session_id=session_id
    )


async def _resume_file_selector(page) -> str | None:
    """CSS selector for the form's file input, if one is present on this step."""
    if await _first_element(page, ['[data-autojob-file="1"]']) is not None:
        return '[data-autojob-file="1"]'
    if await _first_element(page, ['input[type="file"]']) is not None:
        return 'input[type="file"]'
    return None


def _resume_listed_names(info: dict) -> list[str]:
    """Every resume name the form already lists (radio options and select choices)."""
    names = [option.get("label", "") for option in info.get("options", [])]
    select = info.get("select")
    if select:
        names += [choice.get("text", "") for choice in select.get("options", [])]
    return names


async def _click_resume_control(element) -> None:
    """Settle scrolling before browser-use calculates the click coordinates."""
    await element.evaluate(
        "() => this.scrollIntoView({block:'center', inline:'nearest', behavior:'instant'})",
    )
    await asyncio.sleep(0.05)
    await element.click()


async def _attach_resume(
    page,
    session,
    resume_path: str,
    settings: Settings,
    outcome: Task4Outcome,
    notify,
) -> None:
    """Attach the Task 3 resume wherever it is on the dynamic form (Task 4).

    Prefers a resume already listed on the current step (a radio option or a
    ``<select>`` choice); otherwise uploads the file, clicking an "Upload
    resume" button first when that is what reveals the file input.
    """
    emit_step(notify, "Please wait - attaching your resume...")
    info = await read_resume_info(page)
    matched = pick_listed_resume(resume_path, _resume_listed_names(info))

    if matched:
        option = next((o for o in info.get("options", []) if o.get("label") == matched), None)
        if option is not None:
            element = await _marker_element(page, "data-autojob-resume", option["marker"])
            if element is not None:
                await _safe(_click_resume_control(element))
                if settings.session.post_click_wait_seconds:
                    await asyncio.sleep(settings.session.post_click_wait_seconds)
                outcome.resume_attached = True
                outcome.resume_selection = "listed"
                outcome.resume_listed_name = matched
                notify(f"Task 4: selected the listed resume {matched!r}.")
                return

        select = info.get("select")
        choice = (
            next((c for c in select["options"] if c.get("text") == matched), None)
            if select
            else None
        )
        if select is not None and choice is not None:
            element = await _marker_element(page, "data-autojob-resume-select", select["marker"])
            if element is not None:
                await element.evaluate(_FILL_SELECT_JS, str(choice["value"]))
                if settings.session.post_click_wait_seconds:
                    await asyncio.sleep(settings.session.post_click_wait_seconds)
                outcome.resume_attached = True
                outcome.resume_selection = "listed"
                outcome.resume_listed_name = matched
                notify(f"Task 4: selected the listed resume {matched!r}.")
                return

    selector = await _resume_file_selector(page)
    if selector is None and info.get("uploadButton"):
        upload = info["uploadButton"]
        element = await _marker_element(page, "data-autojob-resume-upload", upload["marker"])
        if element is not None:
            await _safe(_click_resume_control(element))
            if settings.session.post_click_wait_seconds:
                await asyncio.sleep(settings.session.post_click_wait_seconds)
            selector = await _resume_file_selector(page)

    if selector is None:
        # The form is dynamic, so the resume control may appear on a later step;
        # record it once (not on every step) but keep looking on subsequent steps.
        note = "no resume control found on this form step"
        if note not in outcome.notes:
            outcome.notes = _append_note(outcome.notes, note)
        return

    outcome.upload_attempted = True
    try:
        await upload_file_via_cdp(session, page, selector, resume_path)
    except Exception as exc:  # noqa: BLE001 - report and continue
        outcome.notes = _append_note(outcome.notes, f"resume upload failed: {exc}")
        return
    if settings.session.post_click_wait_seconds:
        await asyncio.sleep(settings.session.post_click_wait_seconds)
    outcome.resume_attached = True
    outcome.resume_selection = "uploaded"
    notify(f"Task 4: uploaded resume {Path(resume_path).name!r}.")
