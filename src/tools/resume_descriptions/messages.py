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

from .experience_policy import (
    neutralize_experience_requirements,
    profile_for_match,
)
from .match_policy import choose_rated_candidate
from .models import ResumeDescription, ResumeDescriptionError, ResumeMatch

_DESCRIBE_SYSTEM_PROMPT = (
    "You write short, factual profiles of resumes for a resume-matching system. "
    "Read the resume text and reply with ONE JSON object:\n"
    '{"summary": "<one-line summary>", "skills": ["<technology>", ...], '
    '"titles": ["<job title>", ...], "seniority": "<level or empty>", '
    '"years_experience": <number or null>, "domain": "<industry/domain>", '
    '"highlights": ["<factual achievement or responsibility>", ...], '
    '"ai_coding_tools": ["<AI coding assistant/agent>", ...]}\n'
    "Rules:\n"
    "- Use ONLY information found in the resume. Never invent skills, titles, "
    "seniority, years of experience, or a domain.\n"
    "- highlights: up to 6 short, factual statements of the candidate's most "
    "job-relevant achievements or responsibilities, including leadership, "
    "architecture, platform/tooling building, scale, delivery, and production "
    "operations. Copy the resume's facts; do not embellish.\n"
    "- ai_coding_tools: the AI coding assistants/agents the resume explicitly "
    "names (for example Claude Code, Codex, Cursor, GitHub Copilot, Amp); [] if "
    "none are named.\n"
    '- Use [] for missing lists, "" for missing text, and null for missing years.\n'
    "- Keep the summary to a single line."
)

_MATCH_SYSTEM_PROMPT = (
    "You choose the single best-matching resume for a job. You are given the job "
    "description and candidate resumes as a JSON object of id -> profile.\n"
    "Rules:\n"
    "- First rate EVERY candidate, best first: \"strong\" when it genuinely "
    "satisfies the job's core requirements; \"partial\" when it is transferable "
    "but missing core requirements; \"none\" when it is not a reasonable fit. "
    "Put those ratings in `ratings`.\n"
    "- Then choose the strongest candidate. If ANY candidate is strong, your "
    "`choice` MUST be one of the strong candidates and `fit` MUST be \"strong\". "
    "Never choose a merely thematic or partial candidate over a strong one.\n"
    "- If none is strong but ANY candidate is partial, choose the best partial "
    "candidate with fit \"partial\". Both strong and partial matches are eligible "
    "for Easy Apply. Answer \"none\" only when neither rating is available.\n"
    "- Judge by meaning, not exact wording. A candidate with the required stack "
    "and scope is strong even when its job titles differ from the job "
    "title. Seniority may come from the scope of the roles, not only from the "
    "word \"Senior\".\n"
    "- Years-of-experience requirements are NON-BLOCKING. Never compare the "
    "candidate's years of experience with a requested minimum or range, and "
    "never rate a candidate \"partial\" or \"none\" because of a years "
    "shortfall. If the candidate satisfies the core skills/technologies, "
    "domain, and scope/responsibilities, rate it \"strong\" even when the job "
    "asks for more years. Any years figure left in the job text (for example "
    "in company history) is not a fit criterion.\n"
    "- Use skills, titles, seniority, domain, highlights "
    "(leadership, architecture, platforms/tooling, delivery), and "
    "ai_coding_tools when judging fit.\n"
    "- Choose ONLY one of the provided ids. Never invent an id, file name, or path.\n"
    '- If no candidate is a reasonable fit, answer "none" with fit "none".\n'
    "Reply with ONE JSON object: "
    '{"ratings": {"<id>": "<strong|partial|none>", ...}, '
    '"choice": "<id or none>", "fit": "<strong|partial|none>", '
    '"rationale": "<short reason>"}.'
)

_FIT_VALUES = frozenset({"strong", "partial", "none"})


def _normalise_fit(value) -> str:
    """Normalize the model's fit rating (an unknown/missing value becomes ``""``).

    Models often add a qualifier (``"strong fit"``, ``"partially matched"``), so a
    value that starts with a known rating is accepted. Unknown values still fail
    closed (they are not an eligible match).
    """
    fit = str(value or "").strip().lower()
    if fit in _FIT_VALUES:
        return fit
    for candidate in ("strong", "partial", "none"):
        if fit.startswith(candidate):
            return candidate
    return ""


def _fit_ratings(value, ids: dict[str, str]) -> dict[str, str]:
    """Read the model's per-candidate ratings (id -> fit), ignoring unknown ids.

    Accepts both shapes models use: an ordered object (``{"c1": "strong"}``) and
    a list of objects (``[{"id": "c1", "fit": "strong"}]``). Unknown ids are
    dropped, so a hallucinated candidate can never be selected.
    """
    pairs: list[tuple[object, object]] = []
    if isinstance(value, dict):
        pairs = list(value.items())
    elif isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, dict):
                pairs.append((item.get("id"), item.get("fit")))
    ratings: dict[str, str] = {}
    for raw_id, raw_fit in pairs:
        candidate_id = str(raw_id or "").strip()
        if candidate_id in ids:
            ratings[candidate_id] = _normalise_fit(raw_fit)
    return ratings


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
        (
            "summary",
            "skills",
            "titles",
            "seniority",
            "years_experience",
            "domain",
            "highlights",
            "ai_coding_tools",
        ),
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
        # Cap the evidence lists so a verbose reply cannot bloat every match
        # prompt; six highlights and ten tool names are plenty for matching.
        highlights=_string_list(payload.get("highlights"))[:6],
        ai_coding_tools=_string_list(payload.get("ai_coding_tools"))[:10],
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
    lines.append(
        neutralize_experience_requirements(
            job_description.body.strip() or "(no description provided)"
        )
    )
    lines.append("")
    lines.append("Candidate resumes (id -> profile):")
    profiles = {
        f"c{index}": profile_for_match(description)
        for index, (_path, description) in enumerate(candidates, start=1)
    }
    # Compact JSON: the pretty-printed form was several thousand extra characters,
    # which made the model spend longer reading before it answered.
    lines.append(json.dumps(profiles, ensure_ascii=False, separators=(",", ":")))
    lines.append("")
    lines.append("Rate every candidate (best first), then choose the strongest.")
    return [
        {"role": "system", "content": _MATCH_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


def _join_reason(reason: str, extra: str) -> str:
    """Append an audit note to the model's rationale (without a leading ``;``)."""
    reason = (reason or "").strip()
    return f"{reason}; {extra}" if reason else extra


def parse_match(text: str, ids: dict[str, str]) -> ResumeMatch:
    """Turn the model's reply into a :class:`ResumeMatch`.

    Per-candidate ratings decide eligibility: prefer strong, then partial. The
    top-level fit cannot promote an unrated candidate or override its rating.
    Unknown ids are ignored. No eligible rating is a no-match; a reply without
    a decision structure raises instead of silently skipping the job.
    """
    payload = _json_object(text, ("choice", "ratings"))
    if payload is None or not (
        isinstance(payload.get("choice"), str)
        or isinstance(payload.get("ratings"), (dict, list))
    ):
        raise ResumeDescriptionError("the LLM returned an unusable match reply")
    match = ResumeMatch(candidate_ids=dict(ids))
    match.rationale = str(payload.get("rationale") or "").strip()
    reported_fit = _normalise_fit(payload.get("fit"))
    match.ratings = _fit_ratings(payload.get("ratings"), ids)
    choice = str(payload.get("choice") or "").strip()
    choice_id = choice if choice in ids else None
    match.fit = match.ratings.get(choice_id, "") if choice_id else "none"
    selected_id = choose_rated_candidate(choice_id, match.ratings)
    if selected_id is None:
        return match
    previous_fit = match.fit or reported_fit or "unknown"
    match.selected_path = ids[selected_id]
    match.fit = match.ratings[selected_id]
    if selected_id != choice_id:
        match.rationale = _join_reason(
            match.rationale,
            f"the LLM rated {selected_id} {match.fit}; its single choice "
            f"{choice_id or choice or 'none'} was rated {previous_fit}",
        )
    elif reported_fit and reported_fit != match.fit:
        match.rationale = _join_reason(
            match.rationale,
            f"the LLM's {selected_id} rating {match.fit} overrides its "
            f"single-choice fit {reported_fit}",
        )
    return match


__all__ = [
    "build_describe_messages",
    "build_match_messages",
    "candidate_ids",
    "parse_description",
    "parse_match",
]
