"""Task 4: walk the open Easy Apply form step by step, without submitting.

The walk reads each step, fills its known
fields (:mod:`~src.tools.linkedin_easy_apply_fill.field_filling`), attaches the
resume (:mod:`~src.tools.linkedin_easy_apply_fill.resume_attachment`), and
advances via the Next/Continue button until the terminal step (only **Submit
application** remains) or a step stops advancing. It never clicks Submit.
"""

from __future__ import annotations

import asyncio

from src.configuration import Settings
from src.state import JobAnswerContext, Task4Outcome, Task5Outcome
from src.tools.browser import _append_note, _marker_element, _pace, _safe
from src.tools.forms import looks_like_next, pick_next_button
from src.tools.job_context_answers import build_fill_chooser
from src.tools.linkedin_ask_human import ask_human_for_answer
from src.tools.linkedin_easy_apply_fill.field_filling import _choice_hint, _fill_step
from src.tools.linkedin_easy_apply_fill.form_queries import read_form, read_form_buttons
from src.tools.linkedin_easy_apply_fill.resume_attachment import _attach_resume
from src.tools.linkedin_easy_apply_fill.step_state import (
    _blocked_note,
    _blocking_questions,
    _form_signature,
)
from src.tools.linkedin_status_overlay import emit_step
from src.tools.linkedin_validation.conversion_flow import finish_conversions
from src.tools.linkedin_validation.correction import (
    RecheckCorrectedStep,
    RejectedUnknownAnswer,
    failure,
    reject_before_human_prompt,
)
from src.tools.linkedin_validation.detection import read_rejections
from src.tools.linkedin_validation.navigation import finish_advance
from src.tools.linkedin_validation.required_answers import AnswerAttempts
from src.tools.linkedin_validation.required_controls import unanswered_issues
from src.tools.linkedin_validation.skip import persist_and_close
from src.tools.llm_answers import AnswerChooser

from .readiness import _step_when_ready

# How many steps of a multi-step Easy Apply form to walk before stopping. The
# form is dynamic, so this is only a safety cap: the walk stops as soon as there
# is no Next button or the step stops changing.
_MAX_FORM_STEPS = 10


async def _blur_active(page) -> None:
    """Drop focus (and any open autocomplete list) before clicking Next.

    A focused typeahead can swallow the first navigation click while it closes its
    suggestion list; blurring first makes the click land on Next (BUG-056).
    """
    await _safe(
        page.evaluate("() => { const el = document.activeElement; if (el && el.blur) el.blur(); }")
    )


async def _task4_on_page(
    page,
    session,
    resume_path: str | None,
    answers: dict[str, str],
    settings: Settings,
    notify,
    human: Task5Outcome | None = None,
    chooser: AnswerChooser | None = None,
    context: JobAnswerContext | None = None,
) -> Task4Outcome:
    """Fill the open Easy Apply form and attach the resume, without submitting.

    The form is dynamic: its steps, fields, and resume control (radio list,
    ``<select>``, file input, or an upload button that reveals one) are
    discovered at runtime rather than assumed. The walk stops at the terminal
    step (only Submit is left), or as soon as a step fails to advance.

    The LLM chooser matches or derives grounded store answers (Tasks 4.1/10).
    Task 5 asks the human about unknown questions and remembers their answers;
    ``human`` tracks those requests. Task 12's optional ``context`` supplies this
    job's description and selected resume for job-specific answers.
    """
    outcome = Task4Outcome(resume_path=resume_path or "")
    if context is not None:
        outcome.job_context = context.audit()
    human = human if human is not None else Task5Outcome()
    human.enabled = bool(settings.session.ask_human)
    if chooser is None:
        # Task 10/12: prefer match-or-derive from the store, wrapped by the
        # job-context chooser when this fill has a current job context. With no
        # model configured the builders return ``None``, so Task 5 still asks.
        chooser = build_fill_chooser(settings, answers, context)

    asker = None
    if human.enabled:

        async def _ask_question(question: str, field: dict) -> str | None:
            await reject_before_human_prompt(
                page,
                fields,
                question,
                chooser,
                outcome,
                notify,
                corrected_steps,
                signature,
            )
            markers = field.get("markers")
            if markers is None and field.get("marker") is not None:
                markers = [field.get("marker")]
            return await ask_human_for_answer(
                page,
                question,
                field.get("type", ""),
                _choice_hint(field),
                settings,
                notify,
                human,
                markers=markers,
                name=field.get("name"),
                # Only a choice group's option *labels* help identify its controls
                # by question when React drops the marker; a select's options are
                # value/text pairs and play no part in reading the answer.
                options=(
                    field.get("options") if field.get("type") in {"checkbox", "radio"} else None
                ),
            )

        asker = _ask_question

    attempts = AnswerAttempts(settings, human, chooser, asker, notify, answers)
    previous: str | None = None
    pending_advance = False
    blocking: list[str] = []
    corrected_steps: dict[str, bool] = {}

    emit_step(notify, "Please wait - filling the Easy Apply form...")

    for step_index in range(_MAX_FORM_STEPS):
        opened, title, fields, step = await read_form(page)
        if not opened:
            if step_index == 0:
                outcome.notes = _append_note(outcome.notes, "Easy Apply form was not found")
            break

        signature = _form_signature(title, fields, step)
        notify(
            f"Task 4: step {step_index}: {title or '(untitled)'!r} "
            f"fields={len(fields)} step_id={step!r}"
        )
        emit_step(
            notify,
            f"Please wait - filling form step {step_index + 1}{f': {title}' if title else ''}...",
        )
        if pending_advance:
            opened, title, fields, step = await finish_advance(
                page,
                (opened, title, fields, step),
                previous,
                settings,
                notify,
                outcome,
                chooser,
                corrected_steps,
                read=read_form,
                buttons=read_form_buttons,
                signature_of=_form_signature,
                blur=_blur_active,
                required_attempts=attempts,
            )
            signature = _form_signature(title, fields, step)
            if outcome.validation.issues:
                break
            if not opened or signature == previous:
                # The click still did not move to a new step: stop instead of
                # retrying blindly, naming the required fields that still block it.
                outcome.notes = _append_note(
                    outcome.notes, _blocked_note("form did not advance to a new step", blocking)
                )
                break
            outcome.steps_advanced += 1
            pending_advance = False

        # The next step's heading can render before its controls (SDUI). Re-read
        # until the step is actionable instead of mistaking an empty shell for the
        # terminal step (BUG-056).
        opened, title, fields, step, ready, ready_buttons = await _step_when_ready(
            page, settings, opened, title, fields, step
        )
        if not opened:
            outcome.notes = _append_note(
                outcome.notes, "the Easy Apply form closed while its step was rendering"
            )
            break
        if not ready:
            outcome.notes = _append_note(
                outcome.notes,
                "the Easy Apply form did not finish rendering its fields or navigation buttons",
            )
            break
        signature = _form_signature(title, fields, step)
        previous = signature
        attempts.step = signature

        outcome.form_open = True
        outcome.fields_enumerated += len(fields)
        try:
            known, filled, unknown, records = await _fill_step(
                page,
                fields,
                answers,
                settings,
                ask=attempts.ask,
                human=human,
                chooser=attempts.choose,
                status=notify,
            )
        except RecheckCorrectedStep:
            continue
        except RejectedUnknownAnswer as exc:
            outcome.validation = failure(
                exc.issues,
                attempted=exc.attempted,
                reason=exc.reason,
                previous=outcome.validation,
            )
            break
        except Exception as exc:
            issues = unanswered_issues(fields) or [
                {"question": "", "message": "The required answer could not be resolved"},
            ]
            outcome.validation = failure(
                issues, reason=f"answer resolution failed ({type(exc).__name__})",
                previous=outcome.validation,
            )
            break
        outcome.known_fields += known
        outcome.filled_fields += filled
        outcome.unknown_fields.extend(unknown)
        outcome.fields.extend(records)

        if resume_path and not outcome.resume_attached:
            await _attach_resume(page, session, resume_path, settings, outcome, notify)

        buttons = ready_buttons if ready_buttons is not None else await read_form_buttons(page)
        button = pick_next_button(buttons)
        try:
            rejected = await read_rejections(page, fields)
        except Exception as exc:
            outcome.validation = failure(
                unanswered_issues(fields)
                or [{"question": "", "message": "Validation read failed"}],
                reason=f"validation read failed ({type(exc).__name__})",
                previous=outcome.validation,
            )
            break
        if rejected or _blocking_questions(records):
            if any(looks_like_next(b.get("text", "")) for b in buttons):
                outcome.notes = _append_note(
                    outcome.notes,
                    _blocked_note(
                        "the only navigation button is disabled"
                        if button is None
                        else "required questions need an answer",
                        _blocking_questions(records),
                    ),
                )
            current = await finish_advance(
                page,
                (opened, title, fields, step),
                previous,
                settings,
                notify,
                outcome,
                chooser,
                corrected_steps,
                read=read_form,
                buttons=read_form_buttons,
                signature_of=_form_signature,
                blur=_blur_active,
                required_attempts=attempts,
            )
            if outcome.validation.issues:
                break
            if not current[0]:
                outcome.validation = failure(
                    rejected or unanswered_issues(fields),
                    reason="form closed during required-answer recovery",
                    previous=outcome.validation,
                )
                break
            if _form_signature(current[1], current[2], current[3]) != previous:
                pending_advance = True
                continue
            buttons = await read_form_buttons(page)
            button = pick_next_button(buttons)
        if button is None:
            # No enabled Next/Continue on this step. Say *why* we stopped: a
            # disabled navigation button usually means a required answer is
            # missing, otherwise this is the terminal step (only Submit remains).
            blocking = _blocking_questions(records)
            if any(looks_like_next(b.get("text", "")) for b in buttons):
                outcome.notes = _append_note(
                    outcome.notes, _blocked_note("the only navigation button is disabled", blocking)
                )
            else:
                outcome.reached_terminal_step = True
                outcome.notes = _append_note(
                    outcome.notes, "reached the last step (only Submit remains)"
                )
                emit_step(
                    notify,
                    "Application ready at the final review step.",
                )
            break

        element = await _safe(_marker_element(page, "data-autojob-btn", button["marker"]))
        if element is None:
            outcome.notes = _append_note(
                outcome.notes, "navigation button disappeared before it could be clicked"
            )
            break

        blocking = _blocking_questions(records)
        notify(f"Task 4: advancing form step via {button.get('text')!r}.")
        emit_step(notify, f"Please wait - moving on via {button.get('text')!r}...")
        await _blur_active(page)
        await _safe(element.click())
        pending_advance = True
        if settings.session.post_click_wait_seconds:
            await asyncio.sleep(settings.session.post_click_wait_seconds)
        await _pace(settings)
    else:
        # The safety cap was reached without a clear advance/terminal stop: name
        # it instead of ending silently with only "no resume control" (BUG-056).
        outcome.notes = _append_note(
            outcome.notes,
            f"form did not reach the final step within {_MAX_FORM_STEPS} steps",
        )

    if outcome.validation.issues:
        finish_conversions(outcome.validation)
        outcome.validation.required_answer_attempts = attempts.audit()
        outcome.notes = _append_note(
            outcome.notes,
            _blocked_note(
                "form did not advance",
                [issue.question for issue in outcome.validation.issues],
            ),
        )
        await persist_and_close(
            page,
            {"job_description": context.job_description} if context else {},
            outcome,
            settings,
            notify,
        )
    outcome.page_url = await _safe(page.get_url(), None)
    return outcome


def _task4_ok(outcome: Task4Outcome) -> bool:
    return bool(
        outcome.form_open
        and outcome.resume_attached
        and outcome.filled_fields == outcome.known_fields
        and outcome.reached_terminal_step
        and not outcome.submitted
        and not outcome.validation.issues
    )
