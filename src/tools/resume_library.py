"""Task 3.1: the human-provided resume library.

When no resume in the pool matches a job at all, Task 3.1 asks the human for a
resume in the browser. The uploaded file is stored in the resumes folder (so it
joins the pool) and this module remembers which *kind* of job it was provided
for, so a later similar job reuses it without asking again.

A job's *profile* is a small, explainable summary (shared skills, title words,
seniority) built with :mod:`src.tools.matching`; two jobs are "similar" when
their profiles overlap enough. The library is a JSON list, one entry per
remembered resume, and never contains credentials.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.state import JobDescription
from src.tools.matching import find_seniority, skills_in_text, title_tokens

# Accepted resume file formats (case-insensitive). Canonical here; re-exported by
# :mod:`src.tools.linkedin_best_matching_resume` for resume discovery.
RESUME_SUFFIXES = (".pdf", ".docx", ".txt", ".md")

# Two jobs count as "similar" when their profiles overlap at least this much.
REUSE_SIMILARITY_THRESHOLD = 0.3

_SKILL_WEIGHT = 0.7
_TITLE_WEIGHT = 0.3
_SENIORITY_BONUS = 0.1


def job_profile(description: JobDescription) -> dict:
    """A small summary of a job, used to judge similarity (Task 3.1)."""
    text = description.full_text
    return {
        "skills": sorted(skills_in_text(text)),
        "title_tokens": title_tokens(description.title),
        "seniority": find_seniority(description.title) or find_seniority(text),
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def profile_similarity(left: dict, right: dict) -> float:
    """Overlap between two :func:`job_profile` summaries, in ``[0, 1]``."""
    skills = _jaccard(set(left.get("skills") or []), set(right.get("skills") or []))
    titles = _jaccard(
        set(left.get("title_tokens") or []), set(right.get("title_tokens") or [])
    )
    score = _SKILL_WEIGHT * skills + _TITLE_WEIGHT * titles
    if left.get("seniority") and left.get("seniority") == right.get("seniority"):
        score += _SENIORITY_BONUS
    return round(min(score, 1.0), 4)


def load_library(path: str | Path) -> list[dict]:
    """Load the remembered-resume entries (empty when missing/unreadable)."""
    library = Path(path)
    if not library.is_file():
        return []
    try:
        raw = json.loads(library.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict)]


def save_library(path: str | Path, entries: list[dict]) -> None:
    """Write the remembered-resume entries as JSON (creates parent dirs)."""
    library = Path(path)
    library.parent.mkdir(parents=True, exist_ok=True)
    library.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def remember_resume(path: str | Path, description: JobDescription, resume_path: str) -> dict:
    """Remember ``resume_path`` as the resume for jobs like ``description``.

    An existing entry for the same resume file is replaced (so re-remembering does
    not pile up duplicates), and the update is explicit in the returned entry.
    """
    entries = [entry for entry in load_library(path) if entry.get("resume") != str(resume_path)]
    entry = {
        "job_title": description.title,
        "resume": str(resume_path),
        "profile": job_profile(description),
        "added": datetime.now().isoformat(timespec="seconds"),
    }
    entries.append(entry)
    save_library(path, entries)
    return entry


def find_reusable_resume(
    entries: list[dict],
    description: JobDescription,
    resumes_dir: str | Path,
) -> str | None:
    """The remembered resume whose job profile best matches ``description``.

    Only entries whose file still lives in ``resumes_dir`` and overlaps at least
    :data:`REUSE_SIMILARITY_THRESHOLD` count; the best overlap wins.
    """
    current = job_profile(description)
    directory = Path(resumes_dir).resolve()
    best_path: str | None = None
    best_score = 0.0
    for entry in entries:
        resume = str(entry.get("resume") or "")
        if not resume:
            continue
        resume_path = Path(resume)
        try:
            resume_path.resolve().relative_to(directory)
        except ValueError:
            continue  # remembered from a different resumes folder
        if not resume_path.is_file():
            continue  # the file was moved or deleted
        score = profile_similarity(entry.get("profile") or {}, current)
        if score > best_score:
            best_score, best_path = score, resume
    if best_path and best_score >= REUSE_SIMILARITY_THRESHOLD:
        return best_path
    return None


def store_uploaded_resume(resumes_dir: str | Path, filename: str, content: bytes) -> Path:
    """Save an uploaded resume into the pool, never overwriting an existing file.

    Returns the stored path. Raises :class:`ValueError` for an unsupported format
    or empty content, so the caller reports it instead of storing junk.
    """
    name = Path(filename or "resume").name
    stem, suffix = Path(name).stem, Path(name).suffix.lower()
    if suffix not in RESUME_SUFFIXES:
        raise ValueError(f"unsupported resume format: {suffix or '(none)'}")
    if not content:
        raise ValueError("the uploaded resume was empty")
    directory = Path(resumes_dir)
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{stem or 'resume'}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem or 'resume'} ({counter}){suffix}"
        counter += 1
    candidate.write_bytes(content)
    return candidate


__all__ = [
    "RESUME_SUFFIXES",
    "REUSE_SIMILARITY_THRESHOLD",
    "find_reusable_resume",
    "job_profile",
    "load_library",
    "profile_similarity",
    "remember_resume",
    "save_library",
    "store_uploaded_resume",
]
