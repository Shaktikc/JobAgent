"""Task 3.2 prompts and reply parsing.

The model is asked for one JSON object for a resume profile and one JSON object
for the resume choice. Parsing is deliberately forgiving about prose/fences but
strict about the JSON itself: a reply that cannot be read is an error, never a
guess (there is no deterministic fallback).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from src.state import JobDescription

from .models import ResumeDescription, ResumeDescriptionError, ResumeMatch

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


# --- parsing the model's replies -------------------------------------------


def _json_object(text: str, keys: tuple[str, ...] = ()) -> dict | None:
    """Pull the usable JSON object out of a model reply, or ``None``.

    A reply in JSON mode is parsed directly. Otherwise every **balanced** object
    is scanned out of any prose/fence, tracking strings and escapes so a brace
    inside a string cannot swallow the answer. When the reply contains more than
    one object (an example, then the answer), the last object containing one of
    ``keys`` wins. The previous greedy ``\\{.*\\}`` regex failed intermittently
    when the model mentioned any other brace-delimited text.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        payload = None
    if isinstance(payload, dict):
        return payload
    if payload is not None:
        return None

    found: list[dict] = []
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(raw):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
            continue
        if char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    candidate = json.loads(raw[start : index + 1])
                except (ValueError, TypeError):
                    candidate = None
                if isinstance(candidate, dict):
                    found.append(candidate)
                start = None
    if not found:
        return None
    if keys:
        preferred = [item for item in found if any(key in item for key in keys)]
        if preferred:
            return preferred[-1]
    return found[-1]


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
    payload = _json_object(
        text,
        ("summary", "skills", "titles", "seniority", "years_experience", "domain"),
    )
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
    # Compact JSON: the pretty-printed form was several thousand extra characters,
    # which made the model spend longer reading before it answered.
    lines.append(json.dumps(profiles, ensure_ascii=False, separators=(",", ":")))
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
    payload = _json_object(text, ("choice",))
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


__all__ = [
    "build_describe_messages",
    "build_match_messages",
    "candidate_ids",
    "parse_description",
    "parse_match",
]
