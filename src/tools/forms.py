"""Pure helpers for Easy Apply form handling (no I/O, no browser).

These cover resume-name matching (so a resume already listed on the form is
selected instead of uploaded again) and button classification (so the agent can
advance a multi-step form but never click **Submit application**).
"""

from __future__ import annotations

import re
from pathlib import Path

# Phrases that mean "finish the application" — never clicked by the agent.
_SUBMIT_HINTS = (
    "submit application",
    "submit your application",
    "submit",
)

# Phrases on buttons that advance to the next step of a multi-step form.
_NEXT_HINTS = (
    "next",
    "continue",
    "review",
    "save and continue",
    "save & continue",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def normalize_resume_name(value: str) -> str:
    """Reduce a resume file name or path to a comparable key.

    ``ShaktiKC_Resume_python_Node_Senior.pdf`` and ``ShaktiKC Resume python Node
    Senior`` both become ``shaktikcresumepythonnodesenior``.
    """
    stem = Path(value).stem if value else ""
    return re.sub(r"[^a-z0-9]", "", stem.lower())


def pick_listed_resume(chosen: str, listed_names: list[str]) -> str | None:
    """Return the listed resume name matching ``chosen`` (or ``None``).

    Matching is by normalized name; a containment fallback tolerates suffixes
    such as ``(1)`` or a trailing "Selected" label.
    """
    wanted = normalize_resume_name(chosen)
    if not wanted:
        return None
    for name in listed_names:
        if normalize_resume_name(name) == wanted:
            return name
    for name in listed_names:
        candidate = normalize_resume_name(name)
        if candidate and (candidate in wanted or wanted in candidate):
            return name
    return None


def looks_like_submit(text: str) -> bool:
    """True when a button would submit the application."""
    return any(hint in _normalize(text) for hint in _SUBMIT_HINTS)


def looks_like_next(text: str) -> bool:
    """True when a button advances a multi-step form (never a submit button)."""
    normalized = _normalize(text)
    if looks_like_submit(normalized):
        return False
    return any(hint in normalized for hint in _NEXT_HINTS)


def answers_match(option: str, answer: str) -> bool:
    """True when a radio/checkbox option label corresponds to ``answer``."""
    left = _normalize(option)
    right = _normalize(answer)
    if not left or not right:
        return False
    return left == right or left.startswith(right) or right in left


_RESUME_FILENAME_RE = re.compile(r"\.(pdf|docx|txt|md)\b", re.IGNORECASE)


def looks_like_resume_field(question: str, options: list[str] | None = None) -> bool:
    """True for the resume-selection control (handled apart from normal fields)."""
    normalized = _normalize(question)
    if "resume" in normalized:
        return True
    return any(_RESUME_FILENAME_RE.search(option or "") for option in (options or []))


def pick_next_button(buttons: list[dict]) -> dict | None:
    """Return the first non-submit button that advances the form, if any."""
    for button in buttons:
        text = button.get("text", "")
        if looks_like_next(text) and not button.get("disabled"):
            return button
    return None
