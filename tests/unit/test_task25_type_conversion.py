"""A type repair may restate one fact, but may never choose or scale it."""

import pytest

from src.tools.linkedin_validation.type_conversion import conversion_value


def numeric(**constraints):
    return {"kind": "input", "type": "number", "question": "Years of experience*", **constraints}


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("2 years", "2"),
        ("5+", "5"),
        ("~3", "3"),
        ("I have 2 years of experience", "2"),
        ("2.50 years", "2.50"),
        ("0 years", "0"),
        ("-2 years", "-2"),
    ],
)
def test_one_numeric_fact_keeps_its_value(answer, expected):
    assert conversion_value(numeric(step="any"), answer) == expected


@pytest.mark.parametrize(
    "answer",
    [
        "2-3 years",
        "between 2 and 3",
        "2 years and 6 months",
        "24 months",
        "2 million",
        "2k",
        "no experience",
        "not 2 years",
        "2 years in Python and Java",
        "2/3",
        "2%",
    ],
)
def test_ambiguous_or_scaled_answers_are_not_converted(answer):
    assert conversion_value(numeric(), answer) is None


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"inputmode": "numeric"},
        {"inputmode": "decimal"},
        {"pattern": r"[0-9]+"},
        {"pattern": r"^\d+(\.\d+)?$"},
        {"min": "0", "max": "10"},
    ],
)
def test_numeric_expectation_is_discovered_on_text_controls(metadata):
    field = {"kind": "input", "type": "text", "question": "Years of experience*", **metadata}
    assert conversion_value(field, "2 years") == "2"


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("How many years of Python experience?*", "2 years"),
        ("Notice period in weeks*", "2 weeks"),
        ("Number of projects completed*", "2 projects"),
    ],
)
def test_bare_number_uses_only_context_from_the_question(question, expected):
    assert (
        conversion_value({"kind": "textarea", "type": "textarea", "question": question}, "2")
        == expected
    )


@pytest.mark.parametrize(
    "field",
    [
        {"type": "text", "question": "Experience*"},
        {"type": "text", "question": "Years or months of experience*"},
        {"type": "tel", "question": "Phone number*"},
        {"kind": "select", "type": "select", "question": "Years*"},
    ],
)
def test_no_invented_unit_or_choice_rewrite(field):
    assert conversion_value(field, "2") is None


@pytest.mark.parametrize(
    ("constraints", "answer"),
    [
        ({"min": "3"}, "2 years"),
        ({"max": "1"}, "2 years"),
        ({"step": "1"}, "2.5 years"),
        ({"maxlength": 1}, "12 years"),
        ({"minlength": 2}, "2 years"),
        ({"pattern": "[0-9]{2}"}, "2 years"),
    ],
)
def test_discovered_constraints_can_veto_conversion(constraints, answer):
    assert conversion_value(numeric(**constraints), answer) is None


def test_constraint_checks_do_not_round_and_use_the_discovered_step_base():
    assert conversion_value(numeric(min="0.5", step="1"), "2.5 years") == "2.5"
    assert conversion_value(numeric(step="1"), "2.0000000000000000000001 years") is None
    assert conversion_value(numeric(step="1"), "2.00000000000000000000000000001 years") is None
    assert conversion_value({"type": "text", "question": "Years*", "maxlength": 3}, "2") is None
