"""Task 12: Task 9 status text and FormField provenance for context answers."""

from __future__ import annotations

from src.state import FormField
from src.tools.linkedin_status_overlay import emit_llm
from src.tools.llm_answers import QuestionDecision

_ANSWER_PREVIEW_CHARS = 160


def describe_context_sources(sources: list[str]) -> str:
    """Human-readable context source for the Task 9 line."""
    if "resume" in sources and "job_description" in sources:
        return "the job description + your resume"
    if "resume" in sources:
        return "your resume"
    if "job_description" in sources:
        return "the job description"
    return "the job context"


def emit_decision(status, shown: str, decision: QuestionDecision) -> None:
    """Show what the LLM decided on Task 9's line (never the full source text)."""
    if decision.decided:
        answer = (decision.answer or "").strip()
        preview = (
            answer
            if len(answer) <= _ANSWER_PREVIEW_CHARS
            else answer[: _ANSWER_PREVIEW_CHARS - 3] + "..."
        )
        detail = f"{preview!r}"
        if decision.job_specific is True:
            detail += f" (from {describe_context_sources(decision.context_sources)})"
        elif decision.source_summary:
            kind = "derived from" if decision.derived else "from"
            detail += f" ({kind} {decision.source_summary})"
        elif decision.category:
            detail += f" ({decision.category})"
        emit_llm(status, f"answered {shown!r}", detail)
    elif decision.job_specific is True and decision.rationale:
        emit_llm(
            status,
            f"could not ground an answer for {shown!r} - asking you",
            decision.rationale,
        )
    else:
        emit_llm(status, f"no confident answer for {shown!r} - asking you")


def record_decision(record: FormField, decision: QuestionDecision) -> None:
    """Copy a decided answer's provenance onto the run-state field record."""
    if not decision.decided:
        return
    record.question_type = decision.category
    record.matched_key = decision.matched_key
    record.rationale = decision.rationale
    record.derived = decision.derived
    record.source_keys = list(decision.source_keys)
    record.answer_source = decision.context_source
    record.job_specific = decision.job_specific is True
    record.context_evidence = list(decision.evidence)


__all__ = [
    "describe_context_sources",
    "emit_decision",
    "record_decision",
]
