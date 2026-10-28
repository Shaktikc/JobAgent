"""Task 12: deterministic filters for when the job context may answer.

A likely job-specific question is a free-text question about this job, employer,
role, or the applicant's fit for it. The prefilter only *routes* the question;
the LLM's ``job_specific`` decision still confirms it (Subtask 12.2).
"""

from __future__ import annotations

import re

_CHOICE_TYPES = {"radio", "checkbox", "select", "dropdown", "choice"}
_NON_TEXT_TYPES = {
    "number",
    "date",
    "tel",
    "email",
    "url",
    "time",
    "month",
    "week",
    "datetime-local",
    "color",
    "range",
    "file",
    "hidden",
    "password",
}

_JOB_SPECIFIC_PATTERNS = (
    re.compile(
        r"\bwhy\b.*\b(company|employer|organi[sz]ation|role|position|job|us|team|here)\b",
        re.I,
    ),
    re.compile(r"\bwhat\b.*\battract(s|ed|ive)?\b.*\byou\b", re.I),
    re.compile(r"\bwhy do you want\b", re.I),
    re.compile(r"\bwhy are you interested\b", re.I),
    re.compile(r"\bwhat makes you\b.*\b(candidate|fit|match|great|good|strong|ideal)\b", re.I),
    re.compile(r"\bwhy (are|would) you\b.*\b(fit|good|great|strong|ideal)\b", re.I),
    re.compile(r"\bwhat (do|can) you bring\b", re.I),
    re.compile(r"\bcover letter\b", re.I),
    re.compile(r"\b(about you|tell us about yourself|introduce yourself)\b", re.I),
    re.compile(r"\bwhat interests you\b", re.I),
    re.compile(r"\bwhy should we hire you\b", re.I),
    re.compile(r"\bhow do you see yourself\b.*\b(contribut|role|team)\b", re.I),
)

# Factual/personal questions are never answered from the job context, even when
# the store has nothing: they still use the store or Task 5 exactly as before.
_NON_JOB_SPECIFIC_PATTERNS = (
    re.compile(r"\b(salary|compensation|remuneration|pay|package)\b", re.I),
    re.compile(r"\b(city|location|reside|address|relocat)\b", re.I),
    re.compile(r"\b(where are you based|are you based|currently based|based in)\b", re.I),
    re.compile(
        r"\b(work authori[sz]ation|authori[sz]ed to work|eligible to work|right to work|"
        r"work rights|visa|sponsor\w*)\b",
        re.I,
    ),
    re.compile(
        r"\b(notice period|availability|start date|available to start|when can you start)\b",
        re.I,
    ),
    re.compile(r"\b(years? of experience|how many years)\b", re.I),
    re.compile(r"\b(phone|email|date of birth|nationality|citizenship)\b", re.I),
    re.compile(r"\b(clearance|security clearance|legally allowed)\b", re.I),
)


def normalize_text(text: str) -> str:
    """Case/whitespace-normalized text for comparisons and evidence checks."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


def is_choice_control(field_type: str) -> bool:
    """True for a control that only accepts one of its listed options."""
    return normalize_text(field_type) in _CHOICE_TYPES


def is_free_text_field(field_type: str) -> bool:
    """True for a text/textarea control (never a date, number, or choice)."""
    text = normalize_text(field_type)
    if not text or text in {"text", "input", "textarea", "search"}:
        return True
    if is_choice_control(text):
        return False
    return text not in _NON_TEXT_TYPES


def looks_non_job_specific(question: str) -> bool:
    """True for a factual/personal question that the context must never answer."""
    text = normalize_text(question)
    return bool(text) and any(pattern.search(text) for pattern in _NON_JOB_SPECIFIC_PATTERNS)


def looks_job_specific(question: str, field_type: str) -> bool:
    """Deterministic prefilter for likely job-specific free-text questions."""
    if not is_free_text_field(field_type):
        return False
    if looks_non_job_specific(question):
        return False
    text = normalize_text(question)
    return bool(text) and any(pattern.search(text) for pattern in _JOB_SPECIFIC_PATTERNS)


__all__ = [
    "is_choice_control",
    "is_free_text_field",
    "looks_job_specific",
    "looks_non_job_specific",
    "normalize_text",
]
