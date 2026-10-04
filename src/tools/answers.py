"""Persistent question → answer store (Task 4 reads, Task 5 writes).

Task 4 answers any form question it already knows from this store; Task 5 pauses
for the human on unknown questions and saves their answers here. Keys are
normalized (trimmed, lowercased, whitespace collapsed, trailing punctuation
dropped) so near-identical questions reuse the same answer. The store must never
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


def lookup_answer(answers: dict[str, str], candidates: list[str]) -> tuple[str, str] | None:
    """Return ``(key, answer)`` for the first candidate present in ``answers``."""
    for candidate in candidates:
        key = normalize_question(candidate)
        if key and key in answers:
            return key, answers[key]
    return None
