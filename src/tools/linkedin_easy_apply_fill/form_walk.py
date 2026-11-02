"""Task 4: walk the open Easy Apply form step by step, without submitting.

The walk reads each step, fills its known
fields (:mod:`~src.tools.linkedin_easy_apply_fill.field_filling`), attaches the
resume (:mod:`~src.tools.linkedin_easy_apply_fill.resume_attachment`), and
advances via the Next/Continue button until the terminal step (only **Submit
application** remains) or a step stops advancing. It never clicks Submit.
"""

from __future__ import annotations

import asyncio
import time

from src.configuration import Settings
from src.state import FormField, JobAnswerContext, Task4Outcome, Task5Outcome
from src.tools.browser import _append_note, _marker_element, _pace, _safe
from src.tools.forms import looks_like_next, looks_like_submit, pick_next_button
from src.tools.job_context_answers import build_fill_chooser
from src.tools.linkedin_ask_human import ask_human_for_answer
from src.tools.linkedin_easy_apply_fill.field_filling import _choice_hint, _fill_step
from src.tools.linkedin_easy_apply_fill.form_queries import read_form, read_form_buttons
from src.tools.linkedin_easy_apply_fill.resume_attachment import _attach_resume
from src.tools.linkedin_status_overlay import emit_step
from src.tools.llm_answers import AnswerChooser

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


def _blocking_questions(records: list[FormField]) -> list[str]:
    """Required questions on a step that are still unanswered or unfilled.

    A field can be *known* (an answer was chosen) but not *filled* (the click or
    input failed). LinkedIn still blocks **Review**/Next on it, so it must be
    reported alongside a genuinely unknown question.
    """
    blocking: list[str] = []
    for record in records:
        if not record.required or (record.known and record.filled):
            continue
        question = record.question or record.name
        if record.error:
            question = f"{question} ({record.error})"
        if question and question not in blocking:
            blocking.append(question)
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
            f"Please wait - filling form step {step_index + 1}{f': {title}' if title else ''}...",
        )
        if pending_advance:
            if signature == previous:
                # The click can be accepted before the next step renders (LinkedIn
                # shows the review step a moment after Review). Poll for the new
                # step instead of declaring failure on the first read.
                deadline = time.monotonic() + settings.session.easy_apply_timeout_seconds
                while signature == previous and time.monotonic() < deadline:
                    await asyncio.sleep(min(0.5, max(deadline - time.monotonic(), 0)))
                    opened, title, fields, step = await read_form(page)
                    if not opened:
                        break
                    signature = _form_signature(title, fields, step)
                if opened and signature != previous:
                    notify(
                        f"Task 4: step {step_index}: {title or '(untitled)'!r} "
                        f"fields={len(fields)} step_id={step!r}"
                    )
            if not opened or signature == previous:
                # The first click can be swallowed (a transient overlay, a stale
                # handle, or LinkedIn's own saving layer). Re-resolve the current
                # step's Next button and try exactly once before declaring the form
                # stuck; a real validation block still stops after this retry.
                retry_buttons = await read_form_buttons(page)
                retry = pick_next_button(retry_buttons)
                if retry is not None:
                    notify(
                        "Task 4: Next did not advance; retrying once with a fresh button handle."
                    )
                    retry_element = await _marker_element(page, "data-autojob-btn", retry["marker"])
                    if retry_element is not None:
                        await _blur_active(page)
                        await _safe(retry_element.click())
                        if settings.session.post_click_wait_seconds:
                            await asyncio.sleep(settings.session.post_click_wait_seconds)
                        retry_deadline = (
                            time.monotonic() + settings.session.easy_apply_timeout_seconds
                        )
                        while signature == previous and time.monotonic() < retry_deadline:
                            await asyncio.sleep(min(0.5, max(retry_deadline - time.monotonic(), 0)))
                            opened, title, fields, step = await read_form(page)
                            if not opened:
                                break
                            signature = _form_signature(title, fields, step)
                        if opened and signature != previous:
                            notify(
                                f"Task 4: step {step_index}: {title or '(untitled)'!r} "
                                f"fields={len(fields)} step_id={step!r}"
                            )
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

        buttons = ready_buttons if ready_buttons is not None else await read_form_buttons(page)
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
                    "Waiting for you - review and submit the application, then close the browser.",
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

    outcome.page_url = await _safe(page.get_url(), None)
    return outcome


def _task4_ok(outcome: Task4Outcome) -> bool:
    return bool(
        outcome.form_open
        and outcome.resume_attached
        and outcome.filled_fields == outcome.known_fields
        and outcome.reached_terminal_step
        and not outcome.submitted
    )
