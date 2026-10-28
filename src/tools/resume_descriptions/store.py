"""Task 3.2's resume-description store (``data/resume_descriptions.json``).

The store maps a resume's canonical path to its LLM-written profile plus the
file's mtime/size, so an unchanged resume is never re-extracted or re-summarised.
Task 15 can move an entry to a new path after the intake resume is moved into the
main pool. Resume files themselves are never modified here.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from .models import ResumeDescription, ResumeDescriptionError

# Describing resumes is I/O-bound (one LLM call each), so a small pool keeps a
# cold pool fast without hammering the provider. Four matches the usual pool size
# while still bounding a large folder.
DESCRIBE_CONCURRENCY = 4


def canonical_path(resume_path: str | Path) -> str:
    """The canonical key for a resume file (absolute, resolved)."""
    return str(Path(resume_path).resolve())


def _signature(resume_path: str | Path) -> tuple[float, int]:
    stat = Path(resume_path).stat()
    return stat.st_mtime, stat.st_size


def load_descriptions(path: str | Path) -> dict[str, dict]:
    """Load the stored resume descriptions (empty when missing/unreadable)."""
    store = Path(path)
    if not store.is_file():
        return {}
    try:
        raw = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if isinstance(value, dict)}


def save_descriptions(path: str | Path, entries: dict[str, dict]) -> None:
    """Write the resume descriptions as JSON (creates parent dirs)."""
    store = Path(path)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def is_fresh(entry: dict, resume_path: str | Path) -> bool:
    """True when ``entry`` was recorded for the resume's current mtime and size."""
    try:
        mtime, size = _signature(resume_path)
    except OSError:
        return False
    return entry.get("mtime") == mtime and entry.get("size") == size


def _entry_for(resume_path: str | Path, description: ResumeDescription) -> dict:
    """Build the stored entry (profile + the file signature it was built from)."""
    try:
        mtime, size = _signature(resume_path)
    except OSError:
        mtime, size = 0.0, 0
    return {**description.model_dump(), "mtime": mtime, "size": size}


def store_description(
    path: str | Path, resume_path: str | Path, description: ResumeDescription
) -> dict:
    """Save ``description`` for ``resume_path``, replacing any previous entry.

    The resume file itself is never modified; only the sidecar store changes.
    """
    entries = load_descriptions(path)
    entry = _entry_for(resume_path, description)
    entries[canonical_path(resume_path)] = entry
    save_descriptions(path, entries)
    return entry


def description_for(
    entries: dict[str, dict], resume_path: str | Path
) -> ResumeDescription | None:
    """The stored description for ``resume_path``, or ``None`` when absent."""
    entry = entries.get(canonical_path(resume_path))
    if not isinstance(entry, dict):
        return None
    return ResumeDescription.model_validate(entry)


def move_description(
    path: str | Path, old_resume: str | Path, new_resume: str | Path
) -> dict | None:
    """Move a stored description from one resume path to another (Task 15).

    Used after an intake resume is moved into the main pool; the description
    follows the file and the old key is removed so no duplicate/stale entry is
    left behind. Returns the updated entry, or ``None`` when the old path had no
    description.
    """
    entries = load_descriptions(path)
    old_key = canonical_path(old_resume)
    entry = entries.pop(old_key, None)
    if not isinstance(entry, dict):
        return None
    description = ResumeDescription.model_validate(entry)
    updated = _entry_for(new_resume, description)
    entries[canonical_path(new_resume)] = updated
    save_descriptions(path, entries)
    return updated


def described_candidates(
    files: Sequence[str | Path], entries: dict[str, dict]
) -> list[tuple[str, ResumeDescription]]:
    """Build ``(path, description)`` candidates from the pool and the store.

    A resume with no stored description raises: it is an error, never matched from
    its raw text.
    """
    candidates: list[tuple[str, ResumeDescription]] = []
    for path in files:
        description = description_for(entries, path)
        if description is None:
            raise ResumeDescriptionError(f"no stored description for resume {path}")
        candidates.append((str(path), description))
    return candidates


async def ensure_descriptions(
    resumes_dir: str | Path,
    store_path: str | Path,
    settings,
    *,
    files: Sequence[str | Path] | None = None,
    describe: Callable[[str | Path], Awaitable[ResumeDescription]] | None = None,
    client=None,
    extract_text: Callable[[str | Path], str] | None = None,
) -> dict[str, ResumeDescription]:
    """Describe every new/changed resume in the pool; reuse fresh descriptions.

    Fresh entries are reused without any LLM call. The stale/new resumes are
    described **concurrently** (bounded by :data:`DESCRIBE_CONCURRENCY`), which
    turns a cold four-resume pool from four back-to-back calls into one round of
    calls. The store is written once at the end. A resume that cannot be described
    raises (there is no fallback). ``describe`` is injectable for tests.
    """
    if files is None:
        from src.tools.linkedin_best_matching_resume import list_resume_files

        files = list_resume_files(resumes_dir)
    if describe is None:
        from .client import describe_resume

        def describe(path):
            return describe_resume(path, settings, client=client, extract_text=extract_text)

    entries = load_descriptions(store_path)
    described: dict[str, ResumeDescription] = {}
    pending: list[str | Path] = []
    for path in files:
        key = canonical_path(path)
        entry = entries.get(key)
        if isinstance(entry, dict) and is_fresh(entry, path):
            described[key] = ResumeDescription.model_validate(entry)
        else:
            pending.append(path)
    if not pending:
        return described

    semaphore = asyncio.Semaphore(DESCRIBE_CONCURRENCY)

    async def _describe_one(path):
        async with semaphore:
            return await describe(path)

    results = await asyncio.gather(*(_describe_one(path) for path in pending))
    for path, description in zip(pending, results, strict=True):
        entries[canonical_path(path)] = _entry_for(path, description)
        described[canonical_path(path)] = description
    save_descriptions(store_path, entries)
    return described


__all__ = [
    "DESCRIBE_CONCURRENCY",
    "canonical_path",
    "described_candidates",
    "description_for",
    "ensure_descriptions",
    "is_fresh",
    "load_descriptions",
    "move_description",
    "save_descriptions",
    "store_description",
]
