"""Answer only the Easy Apply questions the form marks as required (``*``).

LinkedIn Easy Apply often adds optional diversity/screening questions (ethnicity,
gender, veteran status, ...). They are not needed to submit, yet the fill used to
treat every unanswered control as an unknown question: it paused on it for the
human and could fill it from a stored answer. This module decides which
enumerated fields are required and drops the rest before filling, so only labels
carrying a visible ``*`` marker on their own question/group label
are answered. A dropped control is never asked about, never filled, and never
reported as an unknown question.
"""

from __future__ import annotations

import re

# LinkedIn renders a required question's label with a trailing asterisk
# ("What is your current availability / notice period?*").
_REQUIRED_MARKER_RE = re.compile(r"\*")


def has_required_marker(question: str) -> bool:
    """True when the visible question label carries LinkedIn's ``*`` marker."""
    return bool(_REQUIRED_MARKER_RE.search((question or "").strip()))


def is_required_field(field: dict) -> bool:
    """Only this question's visible label can require an answer.

    HTML required flags and described-by error IDs also appear on voluntary
    LinkedIn questions. They must never override an unstarred label (Task 21).
    """
    return has_required_marker(str(field.get("question") or ""))


def only_required_fields(fields: list[dict]) -> list[dict]:
    """Filter before answering, grouping, persistence or unknown-field accounting.

    Enumeration gives every choice its own group's visible heading. Never spread
    requiredness by name: separate questions can reuse a name. Normalize copies
    for downstream blocking checks without changing the enumerated form state.
    """
    return [dict(field, required=True) for field in fields if is_required_field(field)]


__all__ = [
    "has_required_marker",
    "is_required_field",
    "only_required_fields",
]
