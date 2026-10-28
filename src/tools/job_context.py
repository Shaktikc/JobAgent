"""Task 12.1: build the per-job context used to answer job-specific questions.

The context is the **current** job description plus the resume Task 3 selected
for it. It is rebuilt from scratch for every job (and every self-healed retry),
so a job never inherits the previous job's text. Resume files are only ever read;
this module never renames, moves, or modifies them.

Both source texts are capped before they reach :mod:`job_context_answers`, so a
very long PDF or job page cannot exceed the model's prompt budget. The stored
Task 3.2 profile is included even when the raw resume text is capped or
unavailable. A read failure is recorded on the context and never fails a fill.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.state import JobAnswerContext, JobDescription
from src.tools.linkedin_best_matching_resume import extract_resume_text
from src.tools.resume_descriptions import description_for, load_descriptions

# Maximum characters copied into the prompt for each free-text source. The stored
# profile is small and is always included in addition to these.
MAX_JOB_BODY_CHARS = 6000
MAX_RESUME_TEXT_CHARS = 6000

_TRUNCATED = "\n...[truncated]"

_PROFILE_KEYS = (
    "summary",
    "skills",
    "titles",
    "seniority",
    "years_experience",
    "domain",
)


def _cap(text: str, limit: int) -> str:
    """Trim ``text`` to ``limit`` characters (never raises)."""
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + _TRUNCATED


def _load_profile(descriptions_path, resume_path: str, errors: list[str]) -> dict:
    """Read the resume's stored Task 3.2 profile (best-effort)."""
    if not descriptions_path or not resume_path:
        return {}
    try:
        entries = load_descriptions(descriptions_path)
        profile = description_for(entries, resume_path)
    except Exception as exc:  # noqa: BLE001 - an unreadable store must not fail a fill
        errors.append(f"resume profile read failed: {type(exc).__name__}: {exc}")
        return {}
    if profile is None:
        return {}
    return profile.model_dump()


def _read_resume_text(resume_path: str, errors: list[str], limit: int) -> str:
    """Read the selected resume's text (best-effort; a failure is just recorded)."""
    if not resume_path:
        errors.append("no resume was selected for this job")
        return ""
    try:
        text = extract_resume_text(resume_path)
    except Exception as exc:  # noqa: BLE001 - a bad/corrupt resume must not fail a fill
        errors.append(f"resume read failed: {type(exc).__name__}: {exc}")
        return ""
    if not (text or "").strip():
        errors.append("the selected resume has no readable text")
        return ""
    return _cap(text, limit)


def build_job_context(
    job_description: JobDescription | None,
    resume_path: str | None,
    descriptions_path: str | Path | None = None,
    *,
    max_job_chars: int = MAX_JOB_BODY_CHARS,
    max_resume_chars: int = MAX_RESUME_TEXT_CHARS,
) -> JobAnswerContext:
    """Build the current job + selected resume context for one fill.

    The job body and resume text are capped; the stored Task 3.2 profile is
    loaded when available. Every read problem is recorded in ``errors`` and the
    context is still returned, so the fill proceeds with whatever is available.
    """
    description = (
        job_description.model_copy(deep=True)
        if isinstance(job_description, JobDescription)
        else JobDescription()
    )
    errors: list[str] = []
    if not description.is_read:
        errors.append("the current job description is empty or unreadable")
    description.body = _cap(description.body, max_job_chars)

    path = str(resume_path or "")
    text = _read_resume_text(path, errors, max_resume_chars)
    profile = _load_profile(descriptions_path, path, errors)

    return JobAnswerContext(
        job_description=description,
        resume_path=path,
        resume_text=text,
        resume_profile=profile,
        errors=errors,
    )


def profile_text(profile: dict) -> str:
    """Flatten a stored resume profile into searchable text (values only)."""
    parts: list[str] = []
    for key in _PROFILE_KEYS:
        value = (profile or {}).get(key)
        if isinstance(value, (list, tuple)):
            parts.extend(str(item) for item in value if str(item).strip())
        elif value not in (None, ""):
            parts.append(str(value))
    return " ".join(parts)


def resume_source_text(context: JobAnswerContext) -> str:
    """The resume text used for evidence checks (profile + extracted text)."""
    return " ".join(
        part for part in (profile_text(context.resume_profile), context.resume_text) if part
    )


def job_source_text(context: JobAnswerContext) -> str:
    """The job-description text used for evidence checks."""
    description = context.job_description
    return " ".join(
        part
        for part in (
            description.title,
            description.company,
            description.location,
            description.body,
        )
        if part
    )


def source_text(context: JobAnswerContext, source: str) -> str:
    """Return the text for a claimed context source (empty when unavailable)."""
    if source == "resume":
        return resume_source_text(context)
    if source == "job_description":
        return job_source_text(context)
    return ""


def context_prompt_sources(context: JobAnswerContext) -> str:
    """Render the context's profile for a prompt/debug line (never the raw text)."""
    if not context.resume_profile:
        return "(no stored resume profile)"
    return json.dumps(context.resume_profile, ensure_ascii=False, sort_keys=True)


__all__ = [
    "MAX_JOB_BODY_CHARS",
    "MAX_RESUME_TEXT_CHARS",
    "build_job_context",
    "context_prompt_sources",
    "job_source_text",
    "profile_text",
    "resume_source_text",
    "source_text",
]
