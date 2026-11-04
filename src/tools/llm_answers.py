"""Task 4.1: let the LLM classify each form question and pick the answer to use.

For every question the Easy Apply form asks, the LLM is given:

1. the question text, its field type, and (for choice controls) the options; and
2. the current answer store (``data/answers.json``) as ``question -> answer``;

and it returns the store entry that best answers the question — a short category
and a rationale — or nothing when no stored answer fits. A question with no
chosen answer is left unknown and handed to Task 5.

The model only ever *selects among stored answers*: the answer is resolved from
the store by its normalized key, so the model can never invent an answer. If the
model is unavailable or errors, no answer is chosen (the question goes to
Task 5); there is no deterministic exact-key fallback.

Task 10 extends this by *deriving* an answer the stored entries entail (see
:mod:`src.tools.llm_answer_reasoning`). That chooser records its provenance in
:class:`QuestionDecision` through the ``source_keys`` / ``derived`` /
``source_summary`` fields added here; the select-only chooser leaves them at
their defaults, so its behaviour is unchanged.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from pydantic import BaseModel, Field

from src.configuration import LLMSettings, Settings
from src.llm_model_routing import answer_llm_settings
from src.tools.answers import normalize_question


class QuestionDecision(BaseModel):
    """What the LLM decided about one form question (Task 4.1, Task 10).

    ``matched_key`` records the stored key a copied answer came from. Task 10 adds
    provenance for a *derived* answer: ``source_keys`` are the stored keys the
    answer is grounded in, ``derived`` says it was reasoned from them rather than
    copied, and ``source_summary`` is a short human-readable rendering of those
    sources for Task 9's status line. The select-only chooser (Task 4.1) leaves
    the Task 10 fields at their defaults.
    """

    question: str = ""
    category: str = ""
    answer: str | None = None
    matched_key: str = ""
    rationale: str = ""
    # Task 10: provenance for an answer matched *or* derived from the store.
    source_keys: list[str] = Field(default_factory=list)
    derived: bool = False
    source_summary: str = ""
    # Task 12: provenance for a job-specific answer grounded in the job context.
    job_specific: bool | None = None
    context_sources: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)

    @property
    def context_source(self) -> str:
        """The job-context source(s) recorded on a FormField, e.g. ``resume``."""
        if self.job_specific is not True:
            return ""
        ordered = [
            source
            for source in ("resume", "job_description")
            if source in self.context_sources
        ]
        return "+".join(ordered)

    @property
    def decided(self) -> bool:
        """True when a stored answer was chosen for this question."""
        return bool(self.answer)


class AnswerChooser(Protocol):
    """Callable that picks the answer for a question, or nothing when unknown."""

    async def __call__(
        self, question: str, field_type: str, options: list[str]
    ) -> QuestionDecision: ...


_SYSTEM_PROMPT = (
    "You answer application-form questions for a job applicant. For the question "
    "you are given, first identify what kind of question it is, then decide which "
    "of the applicant's STORED answers (provided as a JSON object of "
    "question -> answer) is the appropriate answer.\n"
    "Rules:\n"
    "- Only choose an answer that already exists in the stored answers. Never "
    "invent an answer or use outside knowledge.\n"
    "- Match by meaning, not exact wording (e.g. 'City' matches 'Location').\n"
    "- For a choice question, prefer a stored answer that matches one of the "
    "listed options.\n"
    "- If no stored answer is appropriate, leave matched_key empty.\n"
    'Reply with ONE JSON object: {"category": "<short question kind>", '
    '"matched_key": "<a key from the stored answers, or empty>", '
    '"rationale": "<short reason>"}.'
)


# The model sometimes wraps JSON in prose or a ```json fence; pull out the first
# balanced-looking object so parsing survives that.
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _dump_answers(answers: dict[str, str]) -> str:
    return json.dumps(answers, ensure_ascii=False, indent=2, sort_keys=True)


def build_messages(
    question: str,
    field_type: str,
    options: list[str],
    answers: dict[str, str],
) -> list[dict[str, str]]:
    """Build the chat messages that ask the model to choose a stored answer."""
    lines = [f"Question: {question}"]
    if field_type:
        lines.append(f"Field type: {field_type}")
    if options:
        lines.append("Allowed options: " + ", ".join(options))
    lines.append("Stored answers (question -> answer):")
    lines.append(_dump_answers(answers))
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


def parse_decision(
    text: str,
    question: str,
    answers: dict[str, str],
) -> QuestionDecision:
    """Turn the model's reply into a :class:`QuestionDecision`.

    The chosen key is normalized and resolved against the store, so an answer
    the model did not take from the store can never be used.
    """
    decision = QuestionDecision(question=question)
    match = _JSON_OBJECT_RE.search(text or "")
    if match is None:
        return decision
    try:
        payload = json.loads(match.group(0))
    except (ValueError, TypeError):
        return decision
    if not isinstance(payload, dict):
        return decision

    decision.category = str(payload.get("category") or "").strip()
    decision.rationale = str(payload.get("rationale") or "").strip()

    key = normalize_question(str(payload.get("matched_key") or ""))
    if not key:
        return decision
    resolved = answers.get(key)
    if resolved is None:
        return decision
    decision.matched_key = key
    decision.answer = resolved
    return decision


class LLMAnswerChooser:
    """An :data:`AnswerChooser` backed by an OpenRouter (OpenAI-compatible) model."""

    def __init__(self, settings: LLMSettings, answers: dict[str, str]) -> None:
        self._settings = settings
        self._answers = answers  # live reference: Task 5 writes into it
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
        """Classify ``question`` and choose a stored answer (never invent one)."""
        if not self._answers:
            return QuestionDecision(question=question)

        messages = build_messages(question, field_type, options, self._answers)
        try:
            client = self._client_or_create()
            response = await client.chat.completions.create(
                model=self._settings.model,
                messages=messages,
                temperature=self._settings.temperature,
            )
            text = (response.choices[0].message.content or "") if response.choices else ""
        except Exception:  # noqa: BLE001 - a bad call leaves the question unknown
            return QuestionDecision(question=question)

        return parse_decision(text, question, self._answers)


def build_answer_chooser(settings: Settings, answers: dict[str, str]) -> AnswerChooser | None:
    """Return the LLM chooser, or ``None`` when no model is configured."""
    llm = answer_llm_settings(settings)
    if not llm.configured:
        return None
    return LLMAnswerChooser(llm, answers)


__all__ = [
    "AnswerChooser",
    "LLMAnswerChooser",
    "QuestionDecision",
    "build_answer_chooser",
    "build_messages",
    "parse_decision",
]
