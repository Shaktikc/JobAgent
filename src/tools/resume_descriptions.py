"""Task 3.2: LLM-written resume descriptions and the LLM resume match.

Subtask 3.2 keeps a short, LLM-written profile for every resume in the pool
(``data/resume_descriptions.json``, keyed by the resume's canonical path) and has
the **LLM** choose the best-matching resume for a job directly from those
descriptions. There is **no deterministic fallback** anywhere in this module: if
the LLM is not configured, the call fails, or the reply is unusable, an error is
raised and the run stops instead of scoring another way.

The module is standalone: it never touches the browser and never modifies a resume
file (only the sidecar store changes). Uploading/attaching the chosen resume stays
Task 4's job.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from src.configuration import LLMSettings, Settings
from src.state import JobDescription


class ResumeDescription(BaseModel):
    """A short, LLM-written profile of one resume (Task 3.2).

    The model only ever summarises what the resume states; a missing field is left
    empty rather than guessed.
    """

    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    seniority: str = ""
    years_experience: int | None = None
    domain: str = ""

    @property
    def usable(self) -> bool:
        """True when the reply actually described the resume (not empty)."""
        return bool(self.summary.strip() or self.skills or self.titles or self.domain.strip())


class ResumeMatch(BaseModel):
    """The LLM's choice of the single best-matching resume (Task 3.2).

    ``selected_path`` is ``None`` when the model answered **none** or named an id
    that is not one of the candidates; ``candidate_ids`` records the id -> path
    map so the decision stays explainable.
    """

    selected_path: str | None = None
    rationale: str = ""
    candidate_ids: dict[str, str] = Field(default_factory=dict)


class ResumeDescriptionError(RuntimeError):
    """Task 3.2 could not describe or match (there is no deterministic fallback)."""


_DESCRIBE_SYSTEM_PROMPT = (
    "You write short, factual profiles of resumes for a resume-matching system. "
    "Read the resume text and reply with ONE JSON object:\n"
    '{"summary": "<one-line summary>", "skills": ["<technology>", ...], '
    '"titles": ["<job title>", ...], "seniority": "<level or empty>", '
    '"years_experience": <number or null>, "domain": "<industry/domain>"}\n'
    "Rules:\n"
    "- Use ONLY information found in the resume. Never invent skills, titles, "
    "seniority, years of experience, or a domain.\n"
    '- Use [] for missing lists, "" for missing text, and null for missing years.\n'
    "- Keep the summary to a single line."
)

_MATCH_SYSTEM_PROMPT = (
    "You choose the single best-matching resume for a job. You are given the job "
    "description and candidate resumes as a JSON object of id -> profile.\n"
    "Rules:\n"
    "- Choose by meaning: compare the job's required skills, title, seniority, and "
    "domain with each candidate's profile.\n"
    "- Choose ONLY one of the provided ids. Never invent an id, file name, or path.\n"
    '- If no candidate is a reasonable fit, answer "none".\n'
    'Reply with ONE JSON object: {"choice": "<id or none>", "rationale": "<short reason>"}.'
)

# The model sometimes wraps JSON in prose or a ```json fence; pull out the first
# balanced-looking object so parsing survives that.
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


# --- the resume-description store (data/resume_descriptions.json) ----------


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


def store_description(
    path: str | Path, resume_path: str | Path, description: ResumeDescription
) -> dict:
    """Save ``description`` for ``resume_path``, replacing any previous entry.

    The resume file itself is never modified; only the sidecar store changes.
    """
    entries = load_descriptions(path)
    try:
        mtime, size = _signature(resume_path)
    except OSError:
        mtime, size = 0.0, 0
    entry = {**description.model_dump(), "mtime": mtime, "size": size}
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


# --- parsing the model's replies -------------------------------------------


def _json_object(text: str) -> dict | None:
    """Pull the first JSON object out of a model reply, or ``None``."""
    match = _JSON_OBJECT_RE.search(text or "")
    if match is None:
        return None
    try:
        payload = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _string_list(value) -> list[str]:
    """Normalise a model-provided list of strings (trim, de-duplicate, drop blanks)."""
    if isinstance(value, str):
        value = re.split(r"[,;]", value)
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _years(value) -> int | None:
    """Read a years-of-experience value from a number or a string like ``"8+"``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 0 else None
    match = re.search(r"(\d{1,2})", str(value))
    return int(match.group(1)) if match else None


def parse_description(text: str) -> ResumeDescription:
    """Turn the model's reply into a :class:`ResumeDescription` (empty if unusable)."""
    payload = _json_object(text)
    if payload is None:
        return ResumeDescription()
    return ResumeDescription(
        summary=str(payload.get("summary") or "").strip(),
        skills=_string_list(payload.get("skills")),
        titles=_string_list(payload.get("titles")),
        seniority=str(payload.get("seniority") or "").strip().lower(),
        years_experience=_years(payload.get("years_experience")),
        domain=str(payload.get("domain") or "").strip(),
    )


def build_describe_messages(resume_text: str) -> list[dict[str, str]]:
    """Build the chat messages that ask the model to describe one resume."""
    return [
        {"role": "system", "content": _DESCRIBE_SYSTEM_PROMPT},
        {"role": "user", "content": f"Resume text:\n{resume_text}"},
    ]


def candidate_ids(candidates: Sequence[tuple[str, ResumeDescription]]) -> dict[str, str]:
    """Map stable ids (``c1``, ``c2``, ...) to resume paths, in order."""
    return {f"c{index}": path for index, (path, _description) in enumerate(candidates, start=1)}


def build_match_messages(
    job_description: JobDescription,
    candidates: Sequence[tuple[str, ResumeDescription]],
    ids: dict[str, str],
) -> list[dict[str, str]]:
    """Build the chat messages that ask the model to pick the best resume."""
    lines = [f"Job title: {job_description.title.strip() or '(untitled)'}"]
    if job_description.company:
        lines.append(f"Company: {job_description.company}")
    if job_description.location:
        lines.append(f"Location: {job_description.location}")
    lines.append("Job description:")
    lines.append(job_description.body.strip() or "(no description provided)")
    lines.append("")
    lines.append("Candidate resumes (id -> profile):")
    profiles = {
        f"c{index}": description.model_dump()
        for index, (_path, description) in enumerate(candidates, start=1)
    }
    lines.append(json.dumps(profiles, ensure_ascii=False, indent=2, sort_keys=True))
    return [
        {"role": "system", "content": _MATCH_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


def parse_match(text: str, ids: dict[str, str]) -> ResumeMatch:
    """Turn the model's reply into a :class:`ResumeMatch`.

    A **none** answer or an id that is not one of the candidates is a no-match
    (``selected_path is None``), never a guess. An unparseable reply raises, because
    there is no deterministic fallback.
    """
    payload = _json_object(text)
    if payload is None:
        raise ResumeDescriptionError("the LLM returned an unusable match reply")
    match = ResumeMatch(candidate_ids=dict(ids))
    match.rationale = str(payload.get("rationale") or "").strip()
    choice = str(payload.get("choice") or "").strip()
    if not choice or choice.lower() == "none":
        return match
    path = ids.get(choice)
    if path is None:
        return match  # invalid choice: treat as no match, never guess
    match.selected_path = path
    return match


# --- the LLM calls ----------------------------------------------------------


def _extract_text(path: str | Path) -> str:
    """Read a resume's text via Task 3's extractor (lazy: avoids an import cycle)."""
    from src.tools.linkedin_best_matching_resume import extract_resume_text

    return extract_resume_text(path)


def _build_client(settings: LLMSettings):
    from openai import AsyncOpenAI  # lazy: only needed when configured

    return AsyncOpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout=settings.timeout_seconds,
        max_retries=settings.max_retries,
    )


async def _chat(client, settings: LLMSettings, messages: list[dict[str, str]]) -> str:
    response = await client.chat.completions.create(
        model=settings.model,
        messages=messages,
        temperature=settings.temperature,
    )
    if not response.choices:
        return ""
    return response.choices[0].message.content or ""


async def describe_resume(
    resume_path: str | Path,
    settings: Settings,
    *,
    client=None,
    extract_text: Callable[[str | Path], str] | None = None,
) -> ResumeDescription:
    """Describe one resume with the LLM, or raise (there is no fallback).

    Raises :class:`ResumeDescriptionError` when the LLM is not configured, the
    resume has no readable text, the call fails, or the reply is unusable.
    """
    if not settings.llm.configured:
        raise ResumeDescriptionError(
            "the LLM is not configured (set OPENROUTER_API_KEY and AUTOJOB_LLM_MODEL)"
        )
    text = (extract_text or _extract_text)(resume_path)
    if not text.strip():
        raise ResumeDescriptionError(f"no readable text in resume {resume_path}")

    client = client or _build_client(settings.llm)
    try:
        reply = await _chat(client, settings.llm, build_describe_messages(text))
    except Exception as exc:  # noqa: BLE001 - surface a clean Task 3.2 error
        raise ResumeDescriptionError(f"the LLM call failed: {exc}") from exc

    description = parse_description(reply)
    if not description.usable:
        raise ResumeDescriptionError("the LLM returned an unusable resume description")
    return description


async def pick_best_resume(
    job_description: JobDescription,
    candidates: Sequence[tuple[str, ResumeDescription]],
    settings: Settings,
    *,
    client=None,
) -> ResumeMatch:
    """Ask the LLM to choose the single best-matching resume, or none.

    An empty candidate list is a no-match without an LLM call. Raises
    :class:`ResumeDescriptionError` when the LLM is not configured or the call fails;
    a **none** answer or an unknown id is returned as a no-match.
    """
    if not candidates:
        return ResumeMatch()
    if not settings.llm.configured:
        raise ResumeDescriptionError(
            "the LLM is not configured (set OPENROUTER_API_KEY and AUTOJOB_LLM_MODEL)"
        )

    ids = candidate_ids(candidates)
    client = client or _build_client(settings.llm)
    messages = build_match_messages(job_description, candidates, ids)
    try:
        reply = await _chat(client, settings.llm, messages)
    except Exception as exc:  # noqa: BLE001 - surface a clean Task 3.2 error
        raise ResumeDescriptionError(f"the LLM call failed: {exc}") from exc
    return parse_match(reply, ids)


async def ensure_descriptions(
    resumes_dir: str | Path,
    store_path: str | Path,
    settings: Settings,
    *,
    files: Sequence[str | Path] | None = None,
    describe: Callable[[str | Path], Awaitable[ResumeDescription]] | None = None,
    client=None,
    extract_text: Callable[[str | Path], str] | None = None,
) -> dict[str, ResumeDescription]:
    """Describe every new/changed resume in the pool; reuse fresh descriptions.

    Returns a mapping of canonical resume path -> description. A resume whose
    stored description is still fresh (same mtime and size) is reused without
    re-extracting or re-summarising it. A resume that cannot be described raises
    (there is no fallback). ``describe`` is injectable for tests.
    """
    if files is None:
        from src.tools.linkedin_best_matching_resume import list_resume_files

        files = list_resume_files(resumes_dir)
    if describe is None:
        def describe(path):
            return describe_resume(path, settings, client=client, extract_text=extract_text)

    entries = load_descriptions(store_path)
    described: dict[str, ResumeDescription] = {}
    for path in files:
        key = canonical_path(path)
        entry = entries.get(key)
        if isinstance(entry, dict) and is_fresh(entry, path):
            described[key] = ResumeDescription.model_validate(entry)
            continue
        description = await describe(path)
        store_description(store_path, path, description)
        described[key] = description
    return described


__all__ = [
    "ResumeDescription",
    "ResumeDescriptionError",
    "ResumeMatch",
    "build_describe_messages",
    "build_match_messages",
    "candidate_ids",
    "canonical_path",
    "describe_resume",
    "described_candidates",
    "description_for",
    "ensure_descriptions",
    "is_fresh",
    "load_descriptions",
    "parse_description",
    "parse_match",
    "pick_best_resume",
    "save_descriptions",
    "store_description",
]
