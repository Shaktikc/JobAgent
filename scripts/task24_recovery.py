"""Run production recovery against the currently rejected real LinkedIn step."""

import json

from src.state import Task4Outcome, Task5Outcome
from src.tools.answers import load_answers
from src.tools.job_context_answers import build_fill_chooser
from src.tools.linkedin_ask_human import ask_human_for_answer
from src.tools.linkedin_easy_apply_fill.field_filling import _choice_hint, _fill_step
from src.tools.linkedin_easy_apply_fill.form_queries import read_form, read_form_buttons
from src.tools.linkedin_easy_apply_fill.form_walk import _blur_active, _form_signature
from src.tools.linkedin_validation.detection import read_rejections
from src.tools.linkedin_validation.navigation import finish_advance
from src.tools.linkedin_validation.required_answers import AnswerAttempts
from src.tools.linkedin_validation.skip import persist_and_close


async def prepare(page, settings, leave_question=""):
    """Fill supported facts only; leave unknown questions for the real human."""
    answers = load_answers(settings.answers_file)
    chooser = build_fill_chooser(settings, answers, None)
    current = await read_form(page)
    fields = [
        field
        for field in current[2]
        if not leave_question or leave_question not in field.get("question", "")
    ]
    known, filled, unknown, _ = await _fill_step(
        page,
        fields,
        answers,
        settings,
        chooser=chooser,
        status=print,
    )
    print(
        "PREPARED:", json.dumps({"known": known, "filled": filled, "unknown": unknown}), flush=True
    )


async def recover(page, settings, mode, folder, timeout):
    current = await read_form(page)
    issues = await read_rejections(page, current[2])
    if not issues:
        raise RuntimeError("Trigger real required validation with Next/Review first")
    settings.session.ask_human = mode == "human"
    settings.session.ask_timeout_seconds = timeout
    human = Task5Outcome()
    answers = load_answers(settings.answers_file)
    chooser = build_fill_chooser(settings, answers, None) if mode == "automatic" else None

    async def ask(question, field):
        return await ask_human_for_answer(
            page,
            question,
            field.get("type", ""),
            _choice_hint(field),
            settings,
            print,
            human,
            markers=field.get("markers"),
            name=field.get("name"),
            options=field.get("options") if field.get("type") in {"radio", "checkbox"} else None,
        )

    attempts = AnswerAttempts(settings, human, chooser, ask, print, answers)
    previous = _form_signature(current[1], current[2], current[3])
    attempts.step = previous
    outcome = Task4Outcome(form_open=True)
    final = await finish_advance(
        page,
        current,
        previous,
        settings,
        print,
        outcome,
        chooser,
        {},
        read=read_form,
        buttons=read_form_buttons,
        signature_of=_form_signature,
        blur=_blur_active,
        required_attempts=attempts,
    )
    if outcome.validation.issues:
        await persist_and_close(page, {}, outcome, settings, print)
    report = {
        "mode": mode,
        "detected_required": [row["question"] for row in issues],
        "advanced": final[0] and _form_signature(final[1], final[2], final[3]) != previous,
        "human_prompts": human.asked,
        "human_answers": human.answered,
        "submitted": outcome.submitted,
        "validation": outcome.validation.model_dump(),
        "attempts": [row.model_dump() for row in attempts.audit()],
    }
    (folder / f"{mode}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("RECOVERY:", json.dumps(report), flush=True)
    assert not outcome.submitted
    assert report["advanced"] or outcome.validation.skipped, report
    return report
