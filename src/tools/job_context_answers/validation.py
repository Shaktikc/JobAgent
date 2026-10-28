"""Task 12.3: ground and validate a job-context answer before it is filled.

An answer is accepted only when every source it claims actually contains one of
its cited evidence snippets, every number appears in the resume or job
description, it does not use a placeholder or merely restate the question, and
(when it asks about the employer) it names the company. A rejected answer is
never filled: it becomes unknown and Task 5 asks the human.
"""

from __future__ import annotations

import re

from src.state import JobAnswerContext
from src.tools.job_context import job_source_text, resume_source_text, source_text
from src.tools.job_context_answers.filters import is_choice_control, normalize_text
from src.tools.llm_answers import QuestionDecision

MAX_ANSWER_CHARS = 1200
MAX_EVIDENCE_CHARS = 400
_CONTEXT_SOURCES = ("resume", "job_description")
_PLACEHOLDER_RE = re.compile(
    r"[\[{]\s*(company|role|employer|job|position|organi[sz]ation)\s*[\]}]", re.I
)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#.-]*")
_STOP_WORDS = {
    "about",
    "after",
    "also",
    "been",
    "being",
    "both",
    "could",
    "does",
    "from",
    "have",
    "into",
    "more",
    "most",
    "only",
    "other",
    "over",
    "should",
    "such",
    "than",
    "that",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "very",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "would",
    "your",
}


def _rejected(decision: QuestionDecision, reason: str) -> QuestionDecision:
    """A job-specific decision that cannot be filled: Task 5 asks the human."""
    return QuestionDecision(
        question=decision.question,
        job_specific=True,
        context_sources=list(decision.context_sources),
        evidence=list(decision.evidence),
        rationale=reason,
    )


def _source_has_evidence(context: JobAnswerContext, source: str, evidence: list[str]) -> bool:
    haystack = normalize_text(source_text(context, source))
    return bool(haystack) and any(
        normalize_text(snippet) and normalize_text(snippet) in haystack for snippet in evidence
    )


def _numbers_supported(answer: str, context: JobAnswerContext) -> bool:
    supported = normalize_text(job_source_text(context) + " " + resume_source_text(context))
    for number in _NUMBER_RE.findall(answer):
        if not re.search(rf"(?<!\d){re.escape(number)}(?!\d)", supported):
            return False
    return True


def _traceable(answer: str, evidence: list[str]) -> bool:
    """True when at least one meaningful answer word appears in the evidence."""
    words = [
        word
        for word in _WORD_RE.findall(normalize_text(answer))
        if len(word) >= 4 and word not in _STOP_WORDS
    ]
    if not words:
        return True
    evidence_text = normalize_text(" ".join(evidence))
    return any(word in evidence_text for word in words)


def _restates_question(answer: str, question: str) -> bool:
    answer_norm = normalize_text(answer).rstrip("?.!* ")
    question_norm = normalize_text(question).rstrip("?.!* ")
    if not answer_norm or not question_norm:
        return False
    if answer_norm == question_norm:
        return True
    return answer_norm.startswith(question_norm) and len(answer_norm) < len(question_norm) + 20


def _asks_about_company(question: str, context: JobAnswerContext) -> bool:
    text = normalize_text(question)
    company = normalize_text(context.job_description.company)
    if company and company in text:
        return True
    return any(
        marker in text
        for marker in ("company", "employer", "organi", "work here", "why us", "join us")
    )


def _company_forms(company: str) -> list[str]:
    """The full company name plus recognizable short forms (brand/legal suffix)."""
    full = normalize_text(company)
    if not full:
        return []
    core = re.sub(
        r"\b(inc|llc|ltd|limited|corp|corporation|company|pty|gmbh|plc)\b\.?",
        " ",
        full,
    )
    core = re.sub(r"\s+", " ", core).strip(" ,.")
    forms = [full]
    if core and core != full:
        forms.append(core)
    tokens = [
        token
        for token in re.split(r"\W+", core)
        if token and token not in {"the", "a", "an", "and", "of", "for"}
    ]
    for candidate in (" ".join(tokens[:2]), tokens[0] if tokens else ""):
        if candidate and len(candidate) >= 3 and candidate not in forms:
            forms.append(candidate)
    return forms


def validate_context_decision(
    decision: QuestionDecision,
    context: JobAnswerContext,
    field_type: str,
    options: list[str] | None = None,
) -> QuestionDecision:
    """Keep a context answer only when it is grounded in its cited evidence."""
    if decision.job_specific is not True:
        return QuestionDecision(
            question=decision.question,
            job_specific=decision.job_specific,
            rationale=decision.rationale,
        )
    if is_choice_control(field_type):
        return _rejected(decision, "a choice control never accepts a prose answer")
    answer = (decision.answer or "").strip()
    if not answer:
        return _rejected(decision, "the model did not provide an answer")
    if len(answer) > MAX_ANSWER_CHARS:
        return _rejected(
            decision, f"the answer is longer than {MAX_ANSWER_CHARS} characters"
        )
    if _PLACEHOLDER_RE.search(answer):
        return _rejected(decision, "the answer contains an unresolved placeholder")
    if _restates_question(answer, decision.question):
        return _rejected(decision, "the answer only restates the question")
    sources = [source for source in decision.context_sources if source in _CONTEXT_SOURCES]
    if not sources:
        return _rejected(decision, "no context source was cited")
    evidence = [snippet for snippet in decision.evidence if normalize_text(snippet)]
    if not evidence:
        return _rejected(decision, "no evidence was cited")
    if any(len(snippet) > MAX_EVIDENCE_CHARS for snippet in evidence):
        return _rejected(decision, "a cited evidence snippet is too long to be a short quote")
    for source in sources:
        if not _source_has_evidence(context, source, evidence):
            return _rejected(
                decision, f"the cited {source} evidence was not found in that source"
            )
    if not _numbers_supported(answer, context):
        return _rejected(
            decision,
            "the answer contains a number not present in the resume or job description",
        )
    if not _traceable(answer, evidence):
        return _rejected(decision, "the answer cannot be traced to its cited evidence")
    company = context.job_description.company.strip()
    if company and _asks_about_company(decision.question, context):
        forms = _company_forms(company)
        if not any(form in normalize_text(answer) for form in forms):
            return _rejected(
                decision, "the answer must name the company from the job description"
            )
    ordered = [source for source in _CONTEXT_SOURCES if source in sources]
    return decision.model_copy(
        update={
            "answer": answer,
            "context_sources": ordered,
            "evidence": evidence,
            "job_specific": True,
        }
    )


__all__ = [
    "MAX_ANSWER_CHARS",
    "validate_context_decision",
]
