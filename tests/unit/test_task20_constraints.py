"""Corrections preserve facts instead of guessing numbers or clipping text."""

import pytest

from src.tools.linkedin_validation.constraints import corrected_value, preserves_facts


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("120,000", "120000"),
        (" 5.0 ", "5.0"),
        ("-3", "-3"),
    ],
)
def test_numeric_format_can_be_repaired(value, expected):
    assert corrected_value({"type": "number", "question": "Amount*"}, value) == expected


def test_numeric_correction_does_not_change_units_or_clamp_values():
    field = {"type": "number", "question": "Years of experience*", "min": "0", "max": "10"}
    assert corrected_value(field, "5 years") == "5"
    assert corrected_value(field, "15 years") is None
    assert corrected_value(field, "60 months") is None
    assert corrected_value(field, "between 3 and 5 years") is None


def test_character_limit_must_not_truncate_factual_numbers():
    assert corrected_value({"type": "number", "maxlength": 3}, "120000") is None
    assert corrected_value({"type": "text", "maxlength": 5}, "abcdef") is None


def test_shorter_equivalent_text_and_existing_valid_value():
    field = {"type": "text", "maxlength": 20, "question": "Relevant tools*"}
    assert corrected_value(field, "  Python    and   SQL  ") == "Python and SQL"
    assert corrected_value(field, "Python and SQL") == "Python and SQL"


def test_range_step_and_pattern_are_respected():
    assert corrected_value({"type": "number", "step": "1"}, "2.5") is None
    assert corrected_value({"type": "number", "min": "0.5", "step": "1"}, "2.5") == "2.5"
    assert corrected_value({"type": "text", "pattern": "[0-9]{3}"}, "abc") is None


def test_utf16_character_limit_matches_browser():
    assert corrected_value({"type": "text", "maxlength": 1}, "😀") is None


def test_grounded_alternative_must_not_change_existing_salary_or_other_facts():
    assert not preserves_facts("120000", "9000")
    assert not preserves_facts("I have no Python experience", "Python experience")
    assert not preserves_facts("I don't have Python experience", "I have Python experience")
    assert not preserves_facts("Python and SQL", "Python and Azure")
    assert not preserves_facts("Python and SQL are my primary tools", "Python and SQL")
    assert not preserves_facts("Available Monday and Friday", "Monday")
    assert preserves_facts("I have Python and SQL experience", "Python and SQL experience")
    assert preserves_facts("120,000", "120000")
