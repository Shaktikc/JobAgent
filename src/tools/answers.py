"""Persistent question → answer store (read during Task 4, written by Task 5).

Task 5 saves the human's answers here; Task 4's LLM reads the whole store and
chooses the appropriate answer for each form question (see
:mod:`src.tools.llm_answers`). Keys are normalized (trimmed, lowercased,
whitespace collapsed, trailing punctuation dropped). The store must never
contain credentials.
"""

from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path

DEFAULT_ANSWERS_FILE = "answers.json"

_TRAILING_PUNCTUATION = " *:?.!"


def normalize_question(text: str) -> str:
    """Canonical key for a form question (case/whitespace/punctuation-insensitive)."""
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    return normalized.rstrip(_TRAILING_PUNCTUATION).strip()


def load_answers(path: str | Path) -> dict[str, str]:
    """Load the store as ``{normalized_question: answer}`` (empty when missing)."""
    answers_file = Path(path)
    if not answers_file.is_file():
        return {}
    try:
        raw = json.loads(answers_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        normalize_question(str(question)): str(answer)
        for question, answer in raw.items()
        if str(question).strip()
    }


def save_answer(path: str | Path, question: str, answer: str) -> str:
    """Store ``question → answer`` (normalized key); return the key used."""
    answers_file = Path(path)
    answers_file.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, str] = {}
    if answers_file.is_file():
        with contextlib.suppress(OSError, ValueError):
            raw = json.loads(answers_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                existing = {str(key): str(value) for key, value in raw.items()}

    key = normalize_question(question)
    existing[key] = answer  # an explicit update overwrites and is recorded
    answers_file.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return key
