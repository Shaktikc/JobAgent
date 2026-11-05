"""Unsafe conversions leave the grounded correction path and original facts intact."""

import json
from types import SimpleNamespace

import pytest

from src.state import Task4Outcome
from src.tools.linkedin_validation import correction
from src.tools.llm_answers import QuestionDecision


@pytest.mark.parametrize(
    ("source", "metadata", "proposed", "expected"),
    [
        (
            "I have Python and SQL experience",
            {"type": "text", "maxlength": 25},
            "Python and SQL experience",
            "Python and SQL experience",
        ),
        ("2-3 years", {"type": "number"}, "3", None),
        ("2 years", {"type": "number", "min": "3"}, "3", None),
    ],
)
async def test_unconvertible_answer_uses_existing_fact_preserving_correction(
    monkeypatch,
    source,
    metadata,
    proposed,
    expected,
):
    field = {
        "question": "Relevant experience*",
        "name": "experience",
        "kind": "input",
        "option": "",
        "required": True,
        "marker": "fresh",
        "value": source,
        **metadata,
    }
    filled = []
    prompts = []

    async def choose(question, kind, options):
        prompts.append(question)
        return QuestionDecision(question=question, answer=proposed, source_keys=["approved"])

    async def read(*args):
        return True, "Questions", [field], "one"

    async def fill(element, current, answer):
        filled.append(answer)
        return True, ""

    async def marker(*args):
        return object()

    monkeypatch.setattr(correction, "_marker_element", marker)
    monkeypatch.setattr("src.tools.linkedin_easy_apply_fill.form_queries.read_form", read)
    monkeypatch.setattr("src.tools.linkedin_easy_apply_fill.field_filling._fill_field", fill)
    outcome = Task4Outcome()
    success, attempted = await correction.correct_rejections(
        None,
        [{"question": field["question"], "message": "Invalid input", "field": field}],
        choose,
        outcome,
        lambda _: None,
    )
    assert success is (expected is not None)
    assert attempted is (expected is not None)
    assert filled == ([] if expected is None else [expected])
    assert len(prompts) == 1
    assert not outcome.validation.type_conversion_attempts[0].attempted
    assert outcome.validation.type_conversion_attempts[0].outcome == "not_possible"


async def test_changed_native_constraints_prevent_entry_after_dom_replacement(monkeypatch):
    field = {
        "question": "Years of experience*",
        "name": "experience",
        "kind": "input",
        "type": "number",
        "option": "",
        "required": True,
        "marker": "old",
        "value": "2 years",
        "min": "0",
        "max": "10",
    }

    async def read(*args):
        return True, "Questions", [{**field, "marker": "replacement"}], "one"

    async def evaluate(*args):
        return json.dumps({"type": "number", "max": "1", "fits": False})

    async def marker(page, attribute, value):
        assert value == "replacement"
        return SimpleNamespace(evaluate=evaluate)

    async def fill(*args):
        pytest.fail("A converted value violating the replacement control must never be entered")

    monkeypatch.setattr(correction, "_marker_element", marker)
    monkeypatch.setattr("src.tools.linkedin_easy_apply_fill.form_queries.read_form", read)
    monkeypatch.setattr("src.tools.linkedin_easy_apply_fill.field_filling._fill_field", fill)
    outcome = Task4Outcome()
    assert await correction.correct_rejections(
        None,
        [{"question": field["question"], "message": "Invalid input", "field": field}],
        None,
        outcome,
        lambda _: None,
    ) == (False, False)
    assert not outcome.validation.type_conversion_attempts[0].attempted


async def test_all_type_repairs_precede_other_fields_grounded_corrections(monkeypatch):
    text = {
        "question": "Relevant tools*",
        "name": "tools",
        "kind": "input",
        "type": "text",
        "option": "",
        "required": True,
        "marker": "tools",
        "maxlength": 25,
        "value": "I have Python and SQL experience",
    }
    numeric = {
        **text,
        "question": "Years of experience*",
        "name": "years",
        "marker": "years",
        "type": "number",
        "value": "2 years",
    }
    entered = []

    async def read(*args):
        return True, "Questions", [text, numeric], "one"

    async def evaluate(*args):
        return json.dumps({"fits": True, "type": "number"})

    async def marker(*args):
        return SimpleNamespace(evaluate=evaluate)

    async def fill(element, field, answer):
        entered.append(answer)
        return True, ""

    async def choose(question, kind, options):
        assert entered == ["2"]
        return QuestionDecision(question=question, answer="Python and SQL experience")

    monkeypatch.setattr(correction, "_marker_element", marker)
    monkeypatch.setattr("src.tools.linkedin_easy_apply_fill.form_queries.read_form", read)
    monkeypatch.setattr("src.tools.linkedin_easy_apply_fill.field_filling._fill_field", fill)
    issues = [
        {"question": f["question"], "message": "Invalid input", "field": f} for f in (text, numeric)
    ]
    assert await correction.correct_rejections(
        None,
        issues,
        choose,
        Task4Outcome(),
        lambda _: None,
    ) == (True, True)
    assert entered == ["2", "Python and SQL experience"]
