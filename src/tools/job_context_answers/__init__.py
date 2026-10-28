"""Task 12.2/12.3: answer job-specific questions from the job context.

The package is split by concern:

- :mod:`.filters` — deterministic job-specific/free-text prefilter.
- :mod:`.prompt` — the LLM prompt and tolerant JSON reply parsing.
- :mod:`.validation` — evidence, number, placeholder, and company grounding.
- :mod:`.chooser` — the LLM call, context-aware routing, and builders.
- :mod:`.presentation` — Task 9 status text and FormField provenance.

This module re-exports the public API so callers import from
:mod:`src.tools.job_context_answers` exactly as before.
"""

from __future__ import annotations

from src.tools.job_context_answers.chooser import (
    ContextAwareAnswerChooser,
    JobContextChooser,
    build_context_answer_chooser,
    build_fill_chooser,
)
from src.tools.job_context_answers.filters import (
    is_choice_control,
    is_free_text_field,
    looks_job_specific,
    looks_non_job_specific,
    normalize_text,
)
from src.tools.job_context_answers.presentation import (
    describe_context_sources,
    emit_decision,
    record_decision,
)
from src.tools.job_context_answers.prompt import (
    build_context_messages,
    parse_context_reply,
)
from src.tools.job_context_answers.validation import (
    MAX_ANSWER_CHARS,
    validate_context_decision,
)

__all__ = [
    "ContextAwareAnswerChooser",
    "JobContextChooser",
    "MAX_ANSWER_CHARS",
    "build_context_answer_chooser",
    "build_context_messages",
    "build_fill_chooser",
    "describe_context_sources",
    "emit_decision",
    "is_choice_control",
    "is_free_text_field",
    "looks_job_specific",
    "looks_non_job_specific",
    "normalize_text",
    "parse_context_reply",
    "record_decision",
    "validate_context_decision",
]
