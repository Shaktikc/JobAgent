"""Task 4: walk the open Easy Apply form step by step, without submitting.

This module owns the step walk, split out of
:mod:`src.tools.linkedin_easy_apply_fill`. It reads each step, fills its known
fields (:mod:`~src.tools.linkedin_easy_apply_fill.field_filling`), attaches the
resume (:mod:`~src.tools.linkedin_easy_apply_fill.resume_attachment`), and
advances via the Next/Continue button until the terminal step (only **Submit
application** remains) or a step stops advancing. It never clicks Submit.
"""

from __future__ import annotations

import asyncio

from src.configuration import Settings
from src.state import FormField, Task4Outcome, Task5Outcome
from src.tools.browser import _append_note, _marker_element, _pace, _safe
from src.tools.forms import looks_like_next, pick_next_button
from src.tools.linkedin_ask_human import ask_human_for_answer
from src.tools.linkedin_easy_apply_fill.field_filling import _choice_hint, _fill_step
from src.tools.linkedin_easy_apply_fill.form_queries import read_form, read_form_buttons
from src.tools.linkedin_easy_apply_fill.resume_attachment import _attach_resume
from src.tools.linkedin_status_overlay import emit_step
from src.tools.llm_answer_reasoning import build_reasoning_answer_chooser
from src.tools.llm_answers import AnswerChooser, build_answer_chooser

# How many steps of a multi-step Easy Apply form to walk before stopping. The
# form is dynamic, so this is only a safety cap: the walk stops as soon as there
# is no Next button or the step stops changing.
_MAX_FORM_STEPS = 10


def _form_signature(title: str, fields: list[dict], step: str = "") -> str:
    """A stable fingerprint of a form step, to detect that Next did not advance.

    ``step`` is the step identity from :func:`read_form` (the modal's progress
    indicator plus its headings). It matters because LinkedIn's review/edit steps
    hold no fillable controls: without ``step``, two such steps would fingerprint
    identically and the walk would stop as if Next had not advanced.
    """
    parts = [title or "", step or ""]
    for field in fields:
        parts.append(
            "|".join(str(field.get(key, "")) for key in ("kind", "question", "name", "option"))
        )
    return "\n".join(parts)


def _blocking_questions(records: list[FormField]) -> list[str]:
    """Required questions on a step that are still unanswered (they block Next)."""
    blocking: list[str] = []
    for record in records:
        if record.required and not record.known and record.question not in blocking:
            blocking.append(record.question)
    return blocking


def _blocked_note(prefix: str, blocking: list[str]) -> str:
    """A clear "why the form stopped" note, naming the required unknown answers."""
    if blocking:
        return (
            f"{prefix}; required questions are unanswered: "
            + ", ".join(blocking)
            + " - stopping before Submit"
        )
    return f"{prefix}; stopping before Submit"


async def _task4_on_page(
    page,
    session,
    resume_path: str | None,
    answers: dict[str, str],
    settings: Settings,
    notify,
    human: Task5Outcome | None = None,
    chooser: AnswerChooser | None = None,
) -> Task4Outcome:
    """Fill the open Easy Apply form and attach the resume, without submitting.

    The form is dynamic: its steps, fields, and resume control (radio list,
    ``<select>``, file input, or an upload button that reveals one) are
    discovered at runtime rather than assumed. The walk stops at the terminal
    step (only Submit is left), or as soon as a step fails to advance.

    Task 4.1 rides along: every question is classified by the LLM, which chooses
    an answer from the store (``chooser``; built from ``settings`` when not
    supplied). Task 10 extends that choice: when a model is configured, the
    reasoning chooser may **match or derive** an answer and must cite the stored
    key(s) it used (see :mod:`src.tools.llm_answer_reasoning`); the select-only
    chooser remains the fallback. Task 5 rides along too: when the LLM cannot
    choose a grounded answer and ``ask_human`` is on, the run pauses on a browser
    banner and reads the answer the human types into the form field. Answers are
    remembered so the same question is answered automatically next time. The
    optional ``human`` tracker records the questions asked, answered, skipped, and
    timed out.
    """
    outcome = Task4Outcome(resume_path=resume_path or "")
    human = human if human is not None else Task5Outcome()
    human.enabled = bool(settings.session.ask_human)
    if chooser is None:
        # Task 10: prefer the match-or-derive chooser when a model is configured;
        # fall back to the select-only chooser (which is also ``None`` when no
        # model is configured, so questions flow to Task 5 unchanged).
        chooser = build_reasoning_answer_chooser(settings, answers) or build_answer_chooser(
            settings, answers
        )

    asker = None
    if human.enabled:

        async def _ask_question(question: str, field: dict) -> str | None:
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
            )

        asker = _ask_question

    previous: str | None = None
    pending_advance = False
    blocking: list[str] = []

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
            f"Please wait - filling form step {step_index + 1}"
            f"{f': {title}' if title else ''}...",
        )
        if pending_advance:
            if signature == previous:
                # The click did not move to a new step: stop instead of retrying
                # blindly, naming the required answers that are still unknown.
                outcome.notes = _append_note(
                    outcome.notes, _blocked_note("form did not advance to a new step", blocking)
                )
                break
            outcome.steps_advanced += 1
            pending_advance = False
        previous = signature

        outcome.form_open = True
        outcome.fields_enumerated += len(fields)
        known, filled, unknown, records = await _fill_step(
            page,
            fields,
            answers,
            settings,
            ask=asker,
            human=human,
            chooser=chooser,
            status=notify,
        )
        outcome.known_fields += known
        outcome.filled_fields += filled
        outcome.unknown_fields.extend(unknown)
        outcome.fields.extend(records)

        if resume_path and not outcome.resume_attached:
            await _attach_resume(page, session, resume_path, settings, outcome, notify)

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
                    "Waiting for you - review and submit the application, "
                    "then close the browser.",
                )
            break

        element = await _marker_element(page, "data-autojob-btn", button["marker"])
        if element is None:
            outcome.notes = _append_note(
                outcome.notes, "navigation button disappeared before it could be clicked"
            )
            break

        blocking = _blocking_questions(records)
        notify(f"Task 4: advancing form step via {button.get('text')!r}.")
        emit_step(notify, f"Please wait - moving on via {button.get('text')!r}...")
        await _safe(element.click())
        pending_advance = True
        if settings.session.post_click_wait_seconds:
            await asyncio.sleep(settings.session.post_click_wait_seconds)
        await _pace(settings)

    outcome.page_url = await _safe(page.get_url(), None)
    return outcome


def _task4_ok(outcome: Task4Outcome) -> bool:
    return bool(
        outcome.form_open
        and outcome.resume_attached
        and outcome.filled_fields == outcome.known_fields
        and not outcome.submitted
    )
