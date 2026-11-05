"""Type repairs share Task 20's single correction pass and navigation retry."""

import json
from types import SimpleNamespace

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task4Outcome
from src.tools.linkedin_validation import correction, navigation, skip


@pytest.mark.parametrize("persistent", [False, True])
async def test_conversion_precedes_chooser_and_uses_one_retry(monkeypatch, persistent):
    field = {
        "kind": "input",
        "type": "text",
        "inputmode": "numeric",
        "required": True,
        "question": "Years of experience*",
        "name": "experience",
        "marker": "fresh",
        "value": "2 years",
        "option": "",
    }
    state = {"clicks": 0, "value": "2 years"}
    outcome = Task4Outcome()

    async def detect(*args):
        return [{"question": field["question"], "message": "Invalid input", "field": field}]

    async def read(*args):
        advanced = state["clicks"] and not persistent
        return True, "Review" if advanced else "Questions", [field], "two" if advanced else "one"

    async def buttons(*args):
        return [{"marker": "next", "text": "Review", "disabled": False}]

    async def click():
        state["clicks"] += 1

    async def evaluate(js, *args):
        return json.dumps({**field, "fits": True})

    async def marker(*args):
        return SimpleNamespace(evaluate=evaluate, click=click)

    async def fill(element, current, answer):
        state["value"] = answer
        return True, ""

    async def chooser(*args):
        pytest.fail("A safe type conversion must run before other corrections")

    async def blur(*args):
        pass

    monkeypatch.setattr(correction, "_marker_element", marker)
    monkeypatch.setattr(navigation, "_marker_element", marker)
    monkeypatch.setattr(navigation, "read_rejections", detect)
    monkeypatch.setattr("src.tools.linkedin_easy_apply_fill.field_filling._fill_field", fill)
    monkeypatch.setattr("src.tools.linkedin_easy_apply_fill.form_queries.read_form", read)
    current = await read()
    result = await navigation.finish_advance(
        None,
        current,
        "one",
        Settings(session=SessionSettings(easy_apply_timeout_seconds=0.001)),
        lambda _: None,
        outcome,
        chooser,
        {},
        read=read,
        buttons=buttons,
        signature_of=lambda title, fields, step: step,
        blur=blur,
    )
    assert state == {"clicks": 1, "value": "2"}
    assert bool(outcome.validation.issues) is persistent
    assert (result[-1] == "two") is not persistent
    audit = outcome.validation.type_conversion_attempts[0]
    assert audit.attempted
    assert audit.direction == "text_to_number"
    assert audit.outcome == ("rejected" if persistent else "accepted")


async def test_skip_record_preserves_conversion_outcome_without_answer_values(
    tmp_path,
    monkeypatch,
):
    from src.state.type_conversion import TypeConversionAttempt
    from src.state.validation import ValidationFailure, ValidationIssue

    async def identity(*args):
        return "123", "https://www.linkedin.com/jobs/view/123/"

    async def close(*args):
        row = json.loads((tmp_path / "invalid_input_skips.json").read_text())[0]
        assert row["type_conversion_attempts"] == [
            {
                "question": "Experience*",
                "direction": "text_to_number",
                "attempted": True,
                "outcome": "rejected",
            }
        ]
        assert "2 years" not in json.dumps(row)
        return True

    monkeypatch.setattr(skip, "current_job_link", identity)
    monkeypatch.setattr(skip, "close_easy_apply_form", close)
    outcome = Task4Outcome(
        validation=ValidationFailure(
            issues=[ValidationIssue(question="Experience*", message="Invalid input")],
            type_conversion_attempts=[
                TypeConversionAttempt(
                    question="Experience*",
                    direction="text_to_number",
                    attempted=True,
                    outcome="rejected",
                )
            ],
        )
    )
    await skip.persist_and_close(None, {}, outcome, Settings(data_dir=tmp_path), lambda _: None)
    assert outcome.validation.skipped


def test_conversion_is_not_accepted_until_navigation_actually_advances():
    from src.state.type_conversion import TypeConversionAttempt
    from src.state.validation import ValidationFailure
    from src.tools.linkedin_validation.conversion_flow import finish_conversions

    validation = ValidationFailure(
        type_conversion_attempts=[
            TypeConversionAttempt(
                question="Years*",
                direction="text_to_number",
                attempted=True,
                outcome="entered",
            )
        ]
    )
    finish_conversions(validation)
    assert validation.type_conversion_attempts[0].outcome == "not_retried"
