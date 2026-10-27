"""Answer only the Easy Apply questions the form marks as required (``*``).

LinkedIn Easy Apply often adds optional diversity/screening questions (ethnicity,
gender, veteran status, ...). They are not needed to submit, yet the fill used to
treat every unanswered control as an unknown question: it paused on it for the
human and could fill it from a stored answer. This module decides which
enumerated fields are required and drops the rest before filling, so only labels
carrying the ``*`` marker (or an explicit ``required``/``aria-required`` signal)
are answered. A dropped control is never asked about, never filled, and never
reported as an unknown question.
"""

from __future__ import annotations

import re

from src.tools.linkedin_easy_apply_fill.checkbox_groups import group_counts, group_key

# LinkedIn renders a required question's label with a trailing asterisk
# ("What is your current availability / notice period?*").
_REQUIRED_MARKER_RE = re.compile(r"\*\s*$")


def has_required_marker(question: str) -> bool:
    """True when the visible question label carries LinkedIn's ``*`` marker."""
    return bool(_REQUIRED_MARKER_RE.search((question or "").strip()))


def is_required_field(field: dict) -> bool:
    """True when this control is required (explicit flag or visible ``*``).

    The enumeration query sets ``required`` from the control's
    ``required``/``aria-required`` attributes and from the label's trailing ``*``
    (BUG-052). Checking the visible label again keeps the rule intact for layouts
    where only the label carries the marker.
    """
    return bool(field.get("required")) or has_required_marker(
        str(field.get("question") or "")
    )


def _choice_group_key(field: dict, counts: dict[str, dict[str, int]]) -> str:
    """A key shared by every option of one radio/checkbox question (or ``""``)."""
    kind = field.get("kind")
    if kind == "radio":
        return "radio:" + str(
            field.get("name") or field.get("question") or field.get("marker")
        )
    if kind == "checkbox":
        return "checkbox:" + group_key(field, counts)
    return ""


def only_required_fields(fields: list[dict]) -> list[dict]:
    """Drop optional questions, keeping every option of a required choice group.

    Requiredness is resolved per group: LinkedIn renders a radio/checkbox question
    as several controls sharing one key, and the question is answered (or skipped)
    as a whole. Any one required option keeps the whole group so the answer can
    select among all its choices.
    """
    counts = group_counts(fields)
    required_groups = {
        key
        for field in fields
        if (key := _choice_group_key(field, counts)) and is_required_field(field)
    }
    kept: list[dict] = []
    for field in fields:
        key = _choice_group_key(field, counts)
        if key:
            if key in required_groups:
                kept.append(field)
        elif is_required_field(field):
            kept.append(field)
    return kept


__all__ = [
    "has_required_marker",
    "is_required_field",
    "only_required_fields",
]
