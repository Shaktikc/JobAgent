"""Task 10.3: remember answers the LLM *derived* from the store.

A derived answer (Task 10.1/10.2) is one the model produced by reasoning over
stored entries rather than copying a stored value verbatim. Caching it keeps the
same question instant and consistent on a later run, with no second LLM call —
and keeps ``data/answers.json`` reserved for answers the human confirmed: Task 5
owns that store and only a human answer goes there.

Each entry records the answer, the stored ``source_keys`` it came from, a
snapshot of those keys' values, and the rationale. An entry is reused only while
its cited sources still exist **and** still hold their snapshotted values;
otherwise it is discarded and re-derived, so a changed store never leaves a stale
answer.

The cache is best-effort: a missing or corrupt file is an empty cache, and a
write failure never fails the run.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from src.tools.answers import normalize_question

DEFAULT_DERIVED_ANSWERS_FILE = "derived_answers.json"


class DerivedAnswer(BaseModel):
    """A cached answer the LLM derived, with the store entries that support it."""

    answer: str = ""
    source_keys: list[str] = Field(default_factory=list)
    source_snapshot: dict[str, str] = Field(default_factory=dict)
    rationale: str = ""


def _entry_from_raw(entry: object) -> DerivedAnswer | None:
    """Build a :class:`DerivedAnswer` from a stored entry, or ``None`` if unusable."""
    if not isinstance(entry, dict):
        return None
    answer = str(entry.get("answer") or "").strip()
    if not answer:
        return None
    raw_keys = entry.get("source_keys")
    keys = [normalize_question(str(key)) for key in (raw_keys or [])]
    raw_snapshot = entry.get("source_snapshot")
    snapshot = {
        normalize_question(str(key)): str(value)
        for key, value in (raw_snapshot.items() if isinstance(raw_snapshot, dict) else [])
    }
    return DerivedAnswer(
        answer=answer,
        source_keys=[key for key in keys if key],
        source_snapshot=snapshot,
        rationale=str(entry.get("rationale") or ""),
    )


def load_derived_answers(path: str | Path) -> dict[str, DerivedAnswer]:
    """Load the derived-answer cache as ``{normalized_question: answer}``.

    A missing or corrupt file loads as an empty cache (never an error).
    """
    cache_file = Path(path)
    if not cache_file.is_file():
        return {}
    try:
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    cache: dict[str, DerivedAnswer] = {}
    for question, entry in raw.items():
        key = normalize_question(str(question))
        if not key:
            continue
        parsed = _entry_from_raw(entry)
        if parsed is not None:
            cache[key] = parsed
    return cache


def supported_by_store(entry: DerivedAnswer, store: dict[str, str]) -> bool:
    """True when every cited source still exists and still holds its snapshot.

    A snapshot is only checked for the keys it recorded, so an older entry with no
    snapshot is accepted while its keys exist.
    """
    if not entry.source_keys:
        return False
    for key in entry.source_keys:
        if key not in store:
            return False
        if key in entry.source_snapshot and entry.source_snapshot[key] != store[key]:
            return False
    return True


def save_derived_answer(
    path: str | Path,
    question: str,
    answer: str,
    source_keys: list[str],
    source_snapshot: dict[str, str] | None = None,
    rationale: str = "",
) -> str | None:
    """Store one derived answer; return its normalized key, or ``None`` if skipped.

    Writes are best-effort: a write error returns ``None`` and never raises. An
    entry identical to the stored one is not written again.
    """
    key = normalize_question(question)
    if not key or not (answer or "").strip():
        return None

    cache_file = Path(path)
    cache = load_derived_answers(cache_file)
    entry = DerivedAnswer(
        answer=str(answer).strip(),
        source_keys=[normalize_question(str(k)) for k in source_keys if str(k).strip()],
        source_snapshot={
            normalize_question(str(k)): str(v)
            for k, v in (source_snapshot or {}).items()
        },
        rationale=str(rationale or ""),
    )
    if cache.get(key) == entry:
        return key  # identical: never write the same entry twice
    cache[key] = entry
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps(
                {question_key: item.model_dump() for question_key, item in cache.items()},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        return None  # best-effort: a write failure never fails the run
    return key


__all__ = [
    "DEFAULT_DERIVED_ANSWERS_FILE",
    "DerivedAnswer",
    "load_derived_answers",
    "save_derived_answer",
    "supported_by_store",
]
