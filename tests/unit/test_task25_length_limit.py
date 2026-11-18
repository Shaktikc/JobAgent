"""Character-limit repairs preserve numeric facts and negations."""

import pytest

from src.tools.linkedin_validation.length_limit import shortening_value


@pytest.mark.parametrize(
    "source,limit,expected",
    [
        ("Experienced software engineer", 20, "Experienced software"),
        ("hello", 5, None),
        ("hello", 9, None),
        ("hello     world", 11, "hello world"),
        ("120000", 3, None),
        ("I do not need sponsorship", 10, None),
        ("Python experience 12 years", 10, None),
        ("hello and more", 9, "hello"),
        ("https://example.com", 8, None),
        ("abcdefghijk", 5, "abcde"),
        ("\U0001f600" * 3, 5, "\U0001f600" * 2),
    ],
)
def test_safe_prefix(source, limit, expected):
    field = {"kind": "input", "type": "text", "required": True, "maxlength": limit}
    assert shortening_value(field, source) == expected


@pytest.mark.parametrize(
    "extra",
    [
        {"minlength": 19},
        {"pattern": "[0-9]+"},
        {"required": False},
        {"type": "number"},
        {"inputmode": "numeric"},
    ],
)
def test_constraints_prevent_entry(extra):
    field = {"kind": "input", "type": "text", "required": True, "maxlength": 10, **extra}
    assert shortening_value(field, "hello wonderful world") is None
