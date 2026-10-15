"""Task 4: fill the fields of one Easy Apply form step.

This module owns the per-field filling logic, split out of
:mod:`src.tools.linkedin_easy_apply_fill`: it keeps a value the form already
holds, asks the LLM (Task 4.1) to choose a stored answer for the rest, falls
back to Task 5's ask-the-human callable when the LLM cannot, and applies the
chosen answer to the real control (text input, ``<select>``, checkbox, or radio)
with React-friendly events.
"""

from __future__ import annotations

from src.configuration import Settings
from src.state import FormField, Task5Outcome
from src.tools.browser import _marker_element, _pace, _safe
from src.tools.forms import answers_match, looks_like_resume_field
from src.tools.linkedin_ask_human import _remember_answer
from src.tools.llm_answers import AnswerChooser, QuestionDecision

# Set a text/textarea value the way React expects (native setter + events).
_FILL_INPUT_JS = r"""
(value) => {
  const proto = this.tagName === 'TEXTAREA'
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(this, value);
  this.dispatchEvent(new Event('input', { bubbles: true }));
  this.dispatchEvent(new Event('change', { bubbles: true }));
  return this.value;
}
"""

# Set a <select> value and fire the change event.
_FILL_SELECT_JS = r"""
(value) => {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
  setter.call(this, value);
  this.dispatchEvent(new Event('change', { bubbles: true }));
  return this.value;
}
"""


# Placeholder values a <select> may show before a real choice is made. A select
# holding one of these is still unanswered; anything else is treated as answered.
_SELECT_PLACEHOLDERS = {
    "",
    "select",
    "select...",
    "select an option",
    "select one",
    "select option",
    "choose",
    "choose an option",
    "choose one",
    "none",
}


def _control_already_answered(field: dict) -> bool:
    """True when a form control already holds a real (non-placeholder) value.

    LinkedIn pre-fills controls from the profile (e.g. the "Email address" and
    "Phone country code" ``<select>``s). Those are already answered, so the agent
    must not ask the human about them or overwrite them with a guess.
    """
    kind = field.get("kind")
    if kind in {"radio", "checkbox"}:
        return bool(field.get("checked"))
    value = str(field.get("value") or "").strip()
    if not value:
        return False
    if kind == "select":
        return value.lower() not in _SELECT_PLACEHOLDERS
    return True


def _choice_hint(field: dict) -> str:
    """Human-readable list of a control's allowed options, for the banner."""
    choices = field.get("options") or []
    labels: list[str] = []
    for choice in choices:
        if isinstance(choice, dict):
            label = str(choice.get("text") or choice.get("value") or "").strip()
        else:
            label = str(choice).strip()
        if label:
            labels.append(label)
    if not labels:
        return ""
    return "One of: " + ", ".join(labels)


def _select_value_for(answer: str, options: list[dict]) -> str | None:
    """Resolve an answer to a ``<select>`` option value (matching text or value)."""
    for option in options:
        text = str(option.get("text") or "")
        value = str(option.get("value") or "")
        if answers_match(text, answer) or answers_match(value, answer):
            return value or text
    return None



async def _fill_field(element, field: dict, answer: str) -> tuple[bool, str]:
    """Fill one known field with the right control action; return ``(ok, error)``."""
    kind = field.get("kind")
    try:
        await _safe(element.evaluate("() => this.scrollIntoView({block: 'center'})"))
        if kind == "select":
            await element.evaluate(_FILL_SELECT_JS, str(answer))
        elif kind == "checkbox":
            if str(answer).strip().lower() in {"yes", "true", "1", "on"}:
                await element.check()
        elif kind == "radio":
            await element.click()
        else:
            await element.evaluate(_FILL_INPUT_JS, str(answer))
        return True, ""
    except Exception as exc:  # noqa: BLE001 - one bad field must not stop the run
        return False, f"{type(exc).__name__}: {exc}"


async def _decide(
    chooser: AnswerChooser | None,
    question: str,
    field_type: str,
    options: list[str],
) -> QuestionDecision:
    """Ask the LLM which stored answer fits ``question`` (Task 4.1).

    With no chooser (no model configured) the question is treated as unknown,
    which hands it to Task 5.
    """
    if chooser is None:
        return QuestionDecision(question=question)
    return await chooser(question, field_type, options)


async def _fill_step(
    page,
    fields: list[dict],
    answers: dict[str, str],
    settings: Settings,
    ask=None,
    human: Task5Outcome | None = None,
    chooser: AnswerChooser | None = None,
) -> tuple[int, int, list[str], list[FormField]]:
    """Fill the known fields of one form step; leave the rest unknown.

    Every question is first classified by the LLM (Task 4.1), which chooses an
    answer from the store. ``ask`` is Task 5's optional async
    ``(question, field) -> answer | None`` callable, used when the LLM cannot
    choose a stored answer (or a chosen radio answer matches none of the step's
    options); a returned answer is filled, remembered in the store, and reused
    for later occurrences.
    """
    known = filled = 0
    unknown: list[str] = []
    records: list[FormField] = []

    # Walk the controls in the order they appear on the form. ``fields`` is in DOM
    # order, so grouping each radio group at its first option asks questions in the
    # order the human sees them — not every choice first, then every text box.
    handled_groups: set[str] = set()

    async def _apply(record: FormField, field: dict, answer: str, source: str) -> None:
        nonlocal known, filled
        record.known = True
        record.value = answer
        record.answered_by = source
        element = await _marker_element(page, "data-autojob-fill", field["marker"])
        if element is None:
            record.error = "field element not found"
        else:
            ok, error = await _fill_field(element, field, answer)
            record.filled = ok
            record.error = error
        known += 1
        filled += 1 if record.filled else 0
        records.append(record)

    for field in fields:
        if field.get("kind") == "radio":
            key = field.get("name") or field.get("question") or field.get("marker")
            if key in handled_groups:
                continue
            handled_groups.add(key)
            group = [
                f
                for f in fields
                if f.get("kind") == "radio"
                and (f.get("name") or f.get("question") or f.get("marker")) == key
            ]
            question = next((g.get("question") for g in group if g.get("question")), "") or key
            options = [g.get("option", "") for g in group if g.get("option")]
            if looks_like_resume_field(question, options):
                continue  # the resume control is handled by _attach_resume
            record = FormField(
                question=question,
                field_type="radio",
                name=key,
                required=any(g.get("required") for g in group),
                options=options,
            )
            checked = next((g for g in group if g.get("checked")), None)
            if checked is not None:
                # Already selected on the form (e.g. a pre-filled choice): leave it be.
                record.known = True
                record.filled = True
                record.value = checked.get("option", "")
                record.answered_by = "form"
                known += 1
                filled += 1
                records.append(record)
                continue
            decision = await _decide(chooser, question, "radio", options)
            answer = decision.answer
            source = "llm" if decision.decided else "human"
            if decision.decided:
                record.question_type = decision.category
                record.matched_key = decision.matched_key
                record.rationale = decision.rationale
            option = (
                next((g for g in group if answers_match(g.get("option", ""), answer)), None)
                if answer is not None
                else None
            )
            # Ask the human only when we have no usable answer: the LLM chose none,
            # or it chose one that matches none of this step's options.
            if option is None and ask is not None:
                group_markers = [g.get("marker") for g in group if g.get("marker")]
                answered = await ask(
                    question,
                    {
                        "type": "radio",
                        "options": options,
                        "markers": group_markers,
                        "name": key,
                    },
                )
                if answered is not None:
                    _remember_answer(settings, answers, human, question, answered)
                    answer, source = answered, "human"
                    record.rationale = ""
                    option = next(
                        (g for g in group if answers_match(g.get("option", ""), answered)), None
                    )
            if option is not None:
                await _apply(record, option, answer, source)
                continue
            if answer is None:
                unknown.append(question)
                records.append(record)
                continue
            record.known = True
            record.value = answer
            record.answered_by = source
            record.error = "no option matched the answer"
            known += 1
            records.append(record)
            continue

        # A non-choice control (text, textarea, select, checkbox).
        question = field.get("question") or field.get("name") or f"field {field.get('marker')}"
        record = FormField(
            question=question,
            option=field.get("option", ""),
            field_type=field.get("type", ""),
            name=field.get("name", ""),
            required=bool(field.get("required")),
            options=[option.get("text", "") for option in field.get("options", [])],
        )
        if _control_already_answered(field):
            # The form already holds a real value (e.g. a pre-filled select): keep it.
            record.known = True
            record.filled = True
            record.value = str(field.get("value") or "")
            record.answered_by = "form"
            known += 1
            filled += 1
            records.append(record)
            continue
        option_labels = [option.get("text", "") for option in field.get("options", [])]
        decision = await _decide(chooser, question, str(field.get("type", "")), option_labels)
        answer = decision.answer
        source = "llm" if decision.decided else "human"
        if decision.decided:
            record.question_type = decision.category
            record.matched_key = decision.matched_key
            record.rationale = decision.rationale
        if answer is None and ask is not None:
            answered = await ask(question, field)
            if answered is not None:
                _remember_answer(settings, answers, human, question, answered)
                answer, source = answered, "human"
                record.rationale = ""
        if answer is None:
            unknown.append(question)
            records.append(record)
            continue
        if field.get("kind") == "select":
            # A <select> only accepts one of its option values, so map the answer
            # (which may be the visible option text) to the real value.
            resolved = _select_value_for(answer, field.get("options") or [])
            if resolved is None and field.get("options"):
                record.error = "the answer did not match any option"
                unknown.append(question)
                records.append(record)
                continue
            if resolved is not None:
                answer = resolved
        if field.get("kind") == "checkbox" and str(answer).strip().lower() in {
            "no",
            "false",
            "0",
            "off",
        }:
            record.known = True
            record.value = answer
            record.filled = True
            record.answered_by = source
            known += 1
            filled += 1
            records.append(record)
            continue
        await _apply(record, field, answer, source)

    await _pace(settings)
    return known, filled, unknown, records
