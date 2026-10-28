"""Task 2b: open Easy Apply only after the resume matcher selects the job.

Task 2's match-first selection leaves the details pane open with the job and its
Easy Apply button visible but the form closed. This module clicks that button
once a resume has been chosen and waits for the form to appear.

Keeping the click separate from selection is what Task 16 needs: a job with no
strong resume match is skipped **without ever clicking Easy Apply**, so there is
no draft to discard and no modal to close.
"""

from __future__ import annotations

from src.configuration import Settings
from src.state import Task2Outcome
from src.tools.browser import _pace, _safe
from src.tools.linkedin import looks_like_easy_apply_action
from src.tools.linkedin_job_apply_button import (
    read_apply_modal,
    wait_for_easy_apply_modal,
    wait_for_job_apply_button,
)
from src.tools.linkedin_status_overlay import emit_step


async def open_easy_apply_form(
    page,
    settings: Settings,
    notify=None,
    outcome: Task2Outcome | None = None,
) -> tuple[bool, Task2Outcome]:
    """Click the selected job's Easy Apply button; return ``(opened, task2)``.

    Idempotent: when a form is already open (for example after a self-healed
    reopen), it is reported as open without clicking again. Only a control whose
    label reads like an Easy Apply action is clicked; an external "Apply on
    company website" button is never used. The agent never clicks **Submit
    application** here.
    """
    notify = notify or (lambda _message: None)
    outcome = outcome or Task2Outcome()
    if page is None:
        outcome.notes = "no browser page to open Easy Apply on"
        return False, outcome

    opened, modal_text = await read_apply_modal(page)
    if opened:
        outcome.easy_apply_button_found = True
        outcome.application_form_opened = True
        outcome.modal_text = modal_text
        return True, outcome

    button, label = await wait_for_job_apply_button(page, settings)
    if button is None or not looks_like_easy_apply_action(label):
        outcome.notes = "no Easy Apply button on the selected job"
        return False, outcome

    outcome.easy_apply_button_found = True
    await _safe(button.evaluate("() => this.scrollIntoView({block: 'center'})"))
    await _pace(settings)
    try:
        await button.click()
    except Exception as exc:  # noqa: BLE001 - report why the form could not open
        outcome.notes = f"Easy Apply click failed: {exc}"
        return False, outcome

    outcome.easy_apply_clicked = True
    await _pace(settings)
    opened, modal_text = await wait_for_easy_apply_modal(page, settings)
    outcome.application_form_opened = opened
    outcome.modal_text = modal_text
    if not opened:
        outcome.notes = "Easy Apply form did not open after the click"
        return False, outcome

    notify("Task 2b: Easy Apply form opened after the resume match.")
    emit_step(
        notify,
        f"Resume matched - opening Easy Apply for {outcome.job_title or 'this job'}...",
    )
    return True, outcome


__all__ = ["open_easy_apply_form"]
