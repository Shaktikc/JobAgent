"""Bounded navigation recovery; validation receives one correction and retry."""

import asyncio
import time

from src.tools.browser import _marker_element
from src.tools.forms import pick_next_button
from src.tools.linkedin_status_overlay import emit_step
from src.tools.linkedin_validation.conversion_flow import finish_conversions, has_conversion
from src.tools.linkedin_validation.correction import correct_rejections, failure
from src.tools.linkedin_validation.detection import read_rejections
from src.tools.linkedin_validation.required_answers import AnswerAttempts, recover_required
from src.tools.linkedin_validation.required_controls import is_missing_issue, unanswered_issues


async def _finish_advance(
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
    required_attempts,
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
                rejected = rejected or required_attempts.unresolved_issues(snapshot[2])
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
        await element.evaluate("() => this.scrollIntoView({block:'center'})")
        await element.click()
        if settings.session.post_click_wait_seconds:
            await asyncio.sleep(settings.session.post_click_wait_seconds)
        return True

    generic_retry_used = False
    while unchanged(current):
        current, issues = await poll(current, stop_on_rejection=True)
        if not unchanged(current):
            return current
        issues = issues or unanswered_issues(current[2])
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
                    previous=outcome.validation,
                )
                return current
            if previous in corrected_steps:
                corrected, attempted = True, True  # Repaired before an unrelated human prompt.
                missing = [row for row in issues if is_missing_issue(row, current[2])
                           and not has_conversion(row, outcome)]
                if missing:
                    corrected, reason = await recover_required(
                        page,
                        missing,
                        outcome,
                        required_attempts,
                        read,
                    )
            else:
                corrected_steps[previous] = False
                emit_step(notify, "Correcting invalid input before retrying this form step...")
                missing = [row for row in issues if is_missing_issue(row, current[2])
                           and not has_conversion(row, outcome)]
                invalid = [row for row in issues if row not in missing]
                corrected, reason = True, ""
                if missing:
                    corrected, reason = await recover_required(
                        page,
                        missing,
                        outcome,
                        required_attempts,
                        read,
                    )
                    attempted = any(
                        row.automatic_attempted or row.human_prompted
                        for row in required_attempts.audit()
                    )
                if corrected and invalid:
                    corrected, tried = await correct_rejections(
                        page,
                        invalid,
                        chooser,
                        outcome,
                        notify,
                    )
                    attempted = attempted or tried
            if not corrected:
                outcome.validation = failure(
                    issues,
                    attempted,
                    reason=reason
                    or "no truthful valid correction was available for every rejected field",
                    previous=outcome.validation,
                )
                return current
            corrected_steps[previous] = True
            emit_step(notify, "Retrying this step once after answering/correcting its questions...")
            retries = int(await click_next())
            current = await read(page)
            current, _ = await poll(current, stop_on_rejection=False)
            if unchanged(current) or not current[0]:
                remaining = await read_rejections(page, current[2]) if current[0] else []
                outcome.validation = failure(
                    remaining or issues, attempted, retries, previous=outcome.validation
                )
            else:
                emit_step(notify, "Invalid input corrected - continuing this application.")
                if any(row.outcome == "entered"
                       for row in outcome.validation.type_conversion_attempts):
                    emit_step(notify, "Type conversion accepted - continuing this application.")
        except Exception as exc:
            # Keep the original rejection even when a chooser/DOM operation
            # fails; losing it would wrongly relaunch structural self-healing.
            outcome.validation = failure(
                issues,
                attempted,
                retries,
                f"validation correction failed ({type(exc).__name__})",
                previous=outcome.validation,
            )
        return current
    return current


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
    required_attempts=None,
):
    """Contain DOM, chooser, banner and navigation failures as validation outcomes."""
    if required_attempts is None:
        from src.state import Task5Outcome

        required_attempts = AnswerAttempts(settings, Task5Outcome(), chooser, None, notify)
        required_attempts.step = previous
    advanced = False
    try:
        result = await _finish_advance(
            page,
            current,
            previous,
            settings,
            notify,
            outcome,
            chooser,
            corrected_steps,
            read=read,
            buttons=buttons,
            signature_of=signature_of,
            blur=blur,
            required_attempts=required_attempts,
        )
        advanced = bool(result[0] and signature_of(result[1], result[2], result[3]) != previous)
        return result
    except Exception as exc:
        issues = [
            {
                "question": field.get("question", ""),
                "message": "Validation could not be read",
                "field": field,
            }
            for field in current[2]
            if field.get("required")
        ]
        outcome.validation = failure(
            issues or [{"question": "", "message": "Validation could not be read"}],
            reason=f"required-answer recovery failed ({type(exc).__name__})",
            previous=outcome.validation,
        )
        return current
    finally:
        finish_conversions(outcome.validation, advanced=advanced)
        if outcome.validation.issues:
            outcome.validation.required_answer_attempts = required_attempts.audit()
