"""Exercise a real rejection using the current field's already-approved fact."""

import asyncio
import json

from src.state import FormField, Task4Outcome
from src.tools.browser import _marker_element
from src.tools.forms import pick_next_button
from src.tools.linkedin_easy_apply_fill.field_filling import _fill_field
from src.tools.linkedin_easy_apply_fill.form_queries import read_form, read_form_buttons
from src.tools.linkedin_easy_apply_fill.form_walk import _blur_active, _form_signature
from src.tools.linkedin_validation.constraints import _number
from src.tools.linkedin_validation.detection import read_rejections
from src.tools.linkedin_validation.navigation import finish_advance
from src.tools.linkedin_validation.type_conversion import conversion_value


async def next_step(page):
    button = pick_next_button(await read_form_buttons(page))
    if button is None:
        raise RuntimeError("No enabled Next/Review control; stopping before Submit")
    element = await _marker_element(page, "data-autojob-btn", button["marker"])
    await _blur_active(page)
    await element.evaluate("() => this.scrollIntoView({block:'center'})")
    await element.click()
    await asyncio.sleep(1)


async def exercise(page, settings, question, folder):
    current = await read_form(page)
    matches = [
        field for field in current[2] if question.casefold() in field.get("question", "").casefold()
    ]
    if len(matches) != 1:
        raise RuntimeError("Select exactly one current numeric question with --exercise")
    field = matches[0]
    # Restate the actual existing answer, never inject a fabricated experience.
    wording = conversion_value(
        {**field, "type": "text", "inputmode": None, "pattern": None, "min": None, "max": None},
        field.get("value") or "",
    )
    if _number(wording or "") is not None and _number(field.get("value") or "") is None:
        wording = field["value"]  # Reproduce an existing rejected factual wording unchanged.
    if wording is None:
        raise RuntimeError("The target must hold an approved number with a unit in its question")
    element = await _marker_element(page, "data-autojob-fill", field["marker"])
    assert (await _fill_field(element, field, wording))[0]
    await next_step(page)
    current = await read_form(page)
    issues = await read_rejections(page, current[2])
    if not any(row["question"] == field["question"] for row in issues):
        raise RuntimeError("The real site did not reject the decorated number")
    (folder / "rejected.html").write_text(
        await page.evaluate(
            "() => document.querySelector('dialog[open],.jobs-easy-apply-modal').outerHTML"
        ),
        encoding="utf-8",
    )
    before = _form_signature(current[1], current[2], current[3])
    outcome = Task4Outcome(
        form_open=True,
        fields=[
            FormField(
                question=field["question"],
                name=field.get("name", ""),
                value=wording,
                known=True,
                filled=True,
            )
        ],
    )
    final = await finish_advance(
        page,
        current,
        before,
        settings,
        print,
        outcome,
        None,
        {},
        read=read_form,
        buttons=read_form_buttons,
        signature_of=_form_signature,
        blur=_blur_active,
    )
    report = {
        "job_url": (await page.get_url()).split("?")[0],
        "question": field["question"],
        "original": wording,
        "advanced": final[0] and _form_signature(final[1], final[2], final[3]) != before,
        "validation": outcome.validation.model_dump(),
        "submitted": outcome.submitted,
    }
    (folder / "conversion.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("CONVERSION:", json.dumps(report), flush=True)
    assert report["advanced"] and not outcome.validation.issues, report
    assert any(row.outcome == "accepted" for row in outcome.validation.type_conversion_attempts)
    assert not outcome.submitted
