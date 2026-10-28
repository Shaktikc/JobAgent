"""Task 12: the job-context LLM call and the context-aware answer routing."""

from __future__ import annotations

from src.configuration import LLMSettings, Settings
from src.state import JobAnswerContext
from src.tools.answers import normalize_question
from src.tools.job_context_answers.filters import (
    is_choice_control,
    is_free_text_field,
    looks_job_specific,
    looks_non_job_specific,
)
from src.tools.job_context_answers.prompt import (
    build_context_messages,
    parse_context_reply,
)
from src.tools.job_context_answers.validation import validate_context_decision
from src.tools.llm_answer_reasoning import build_reasoning_answer_chooser
from src.tools.llm_answers import AnswerChooser, QuestionDecision, build_answer_chooser


class JobContextChooser:
    """Ask the LLM for a job-specific answer grounded in one job context."""

    def __init__(self, settings: LLMSettings, context: JobAnswerContext) -> None:
        self._settings = settings
        self._context = context
        self._client = None

    def _client_or_create(self):
        if self._client is None:
            from openai import AsyncOpenAI  # lazy: only needed when configured

            self._client = AsyncOpenAI(
                api_key=self._settings.api_key,
                base_url=self._settings.base_url,
                timeout=self._settings.timeout_seconds,
                max_retries=self._settings.max_retries,
            )
        return self._client

    async def __call__(
        self, question: str, field_type: str, options: list[str]
    ) -> QuestionDecision:
        """Answer ``question`` from the context, or return an unknown decision."""
        if not is_free_text_field(field_type) or is_choice_control(field_type):
            return QuestionDecision(question=question, job_specific=False)
        if looks_non_job_specific(question):
            return QuestionDecision(question=question, job_specific=False)
        if not self._context.sources:
            return QuestionDecision(
                question=question,
                job_specific=True,
                rationale="no job context source is available",
            )
        messages = build_context_messages(question, field_type, options, self._context)
        try:
            client = self._client_or_create()
            response = await client.chat.completions.create(
                model=self._settings.model,
                messages=messages,
                temperature=self._settings.temperature,
            )
            text = (response.choices[0].message.content or "") if response.choices else ""
        except Exception as exc:  # noqa: BLE001 - a bad call leaves it to Task 5
            return QuestionDecision(
                question=question,
                job_specific=True,
                rationale=f"the job-context LLM call failed: {type(exc).__name__}",
            )
        decision = parse_context_reply(text, question)
        if decision.job_specific is None:
            return QuestionDecision(
                question=question,
                job_specific=True,
                rationale="the job-context LLM reply was unusable",
            )
        return validate_context_decision(decision, self._context, field_type, options)


class ContextAwareAnswerChooser:
    """Route each question to the human answer store or the job context.

    Precedence (Task 12.3): exact human-confirmed answer → likely job-specific
    free-text question → store chooser → context fallback for other free-text
    questions → unknown for Task 5.
    """

    def __init__(
        self,
        context: JobAnswerContext,
        settings: LLMSettings,
        answers: dict[str, str],
        store_chooser: AnswerChooser | None = None,
    ) -> None:
        self._context = context
        self._answers = answers
        self._store = store_chooser
        self._context_chooser = JobContextChooser(settings, context)

    def _exact(self, question: str) -> QuestionDecision | None:
        key = normalize_question(question)
        answer = str(self._answers.get(key) or "").strip()
        if not answer:
            return None
        return QuestionDecision(
            question=question,
            answer=answer,
            matched_key=key,
            source_keys=[key],
            source_summary=f"'{key}': {answer!r}",
        )

    async def _store_decision(
        self, question: str, field_type: str, options: list[str]
    ) -> QuestionDecision:
        if self._store is None:
            return QuestionDecision(question=question)
        return await self._store(question, field_type, options)

    async def _context_decision(
        self, question: str, field_type: str, options: list[str]
    ) -> QuestionDecision:
        """Never let a context failure escape into the form walk."""
        try:
            decision = await self._context_chooser(question, field_type, options)
            if decision.job_specific is True and decision.decided:
                # Defense in depth: a swapped/custom context chooser must still
                # pass the same grounding guard before prose reaches a control.
                return validate_context_decision(
                    decision, self._context, field_type, options
                )
            return decision
        except Exception as exc:  # noqa: BLE001 - Task 5 is the safe fallback
            return QuestionDecision(
                question=question,
                job_specific=True,
                rationale=f"the job-context chooser failed: {type(exc).__name__}",
            )

    async def __call__(
        self, question: str, field_type: str, options: list[str]
    ) -> QuestionDecision:
        exact = self._exact(question)
        if exact is not None:
            return exact  # the human's answer always wins

        tried_context = False
        if looks_job_specific(question, field_type):
            tried_context = True
            decision = await self._context_decision(question, field_type, options)
            if decision.decided:
                return decision
            if decision.job_specific is True:
                # Likely job-specific but ungrounded: Task 5, never stale prose.
                return decision

        decision = await self._store_decision(question, field_type, options)
        if decision.decided:
            return decision
        if not tried_context and is_free_text_field(field_type):
            if not looks_non_job_specific(question):
                fallback = await self._context_decision(question, field_type, options)
                if fallback.decided:
                    return fallback
                if fallback.job_specific is True:
                    return fallback
        return QuestionDecision(question=question)


def build_context_answer_chooser(
    settings: Settings,
    answers: dict[str, str],
    context: JobAnswerContext,
    store_chooser: AnswerChooser | None = None,
) -> ContextAwareAnswerChooser | None:
    """Return the context-aware chooser, or ``None`` when no model is configured."""
    if not settings.llm.configured:
        return None
    store_chooser = (
        store_chooser
        or build_reasoning_answer_chooser(settings, answers)
        or build_answer_chooser(settings, answers)
    )
    return ContextAwareAnswerChooser(context, settings.llm, answers, store_chooser)


def build_fill_chooser(
    settings: Settings, answers: dict[str, str], context: JobAnswerContext | None
) -> AnswerChooser | None:
    """Build the chooser Task 4 uses, wrapping the store chooser when possible."""
    store_chooser = build_reasoning_answer_chooser(settings, answers) or build_answer_chooser(
        settings, answers
    )
    if context is None:
        return store_chooser
    return build_context_answer_chooser(settings, answers, context, store_chooser) or store_chooser


__all__ = [
    "ContextAwareAnswerChooser",
    "JobContextChooser",
    "build_context_answer_chooser",
    "build_fill_chooser",
]
