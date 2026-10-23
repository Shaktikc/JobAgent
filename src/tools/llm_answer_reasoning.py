"""Task 10: answer a form question from the store by *matching or deriving*.

:mod:`src.tools.llm_answers` (Task 4.1) can only **copy** a stored answer, so a
question the store plainly entails but does not literally contain is reported
unknown — e.g. the store holds ``"years of experience ... (ai)": "5"`` while the
form asks ``"Experience on AI? [Yes/No]"``, so no stored value is ``"Yes"``.

This module relaxes that carefully. The model may **match** (copy a stored answer
whose meaning answers the question) or **derive** (produce a short answer the
stored entries *entail*, e.g. positive years ⇒ ``"Yes"``), and must cite the
stored key(s) it used. :func:`validate_decision` is the pure guard that preserves
the no-invention promise: it rejects an answer with no existing cited source, a
derive the cited values do not entail, or a choice answer that maps to none of the
question's options. A rejected decision becomes *unknown* and flows to Task 5
unchanged, so the fallback is always "ask the human", never a guess. An accepted
derive is cached (Task 10.3, :mod:`src.tools.derived_answers`) for next time.
"""

from __future__ import annotations

import json
import re

from src.configuration import LLMSettings, Settings
from src.tools.answers import normalize_question
from src.tools.derived_answers import (
    DerivedAnswer,
    load_derived_answers,
    save_derived_answer,
    supported_by_store,
)
from src.tools.forms import answers_match
from src.tools.llm_answers import QuestionDecision

_SYSTEM_PROMPT = (
    "You answer application-form questions for a job applicant using ONLY the "
    "applicant's STORED answers, given as a JSON object of question -> answer.\n"
    "Choose the answer in one of two ways:\n"
    "1. MATCH: copy a stored answer whose meaning answers the question, matching "
    "by meaning rather than exact wording (e.g. 'City' matches 'Location').\n"
    "2. DERIVE: when no stored value can be copied verbatim, produce a short "
    "answer that the stored entries ENTAIL (e.g. a positive 'years of experience' "
    "entry entails 'Yes' for a yes/no experience question).\n"
    "Rules:\n"
    "- Never use outside knowledge and never invent an answer; every answer must "
    "be copied from, or entailed by, the stored answers you cite.\n"
    "- List every stored key you relied on in source_keys; each must be one of the "
    "stored questions.\n"
    "- If no stored entry supports an answer, return an empty answer and an empty "
    "source_keys list.\n"
    "- For a choice question the answer must be one of the listed options.\n"
    'Reply with ONE JSON object: {"category": "<short question kind>", '
    '"answer": "<the answer to use, or empty>", '
    '"source_keys": ["<stored keys you used>"], "rationale": "<short reason>"}.'
)

# The model sometimes wraps JSON in prose or a ```json fence; pull out the first
# balanced-looking object so parsing survives that.
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

# A derived answer is meant to be short; a long one is treated as a fabrication
# risk and rejected rather than filled (Task 10.2).
_MAX_DERIVED_TEXT = 200

# Values a stored entry (or a derived answer) may use to mean yes or no. The
# canonical meanings let a derive canonicalise to a question's option label.
_YES_SYNONYMS = {"yes", "y", "true", "yeah", "yep", "sure", "correct", "affirmative"}
_NO_SYNONYMS = {"no", "n", "false", "nope", "never"}
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _dump_answers(answers: dict[str, str]) -> str:
    return json.dumps(answers, ensure_ascii=False, indent=2, sort_keys=True)


def build_reasoning_messages(
    question: str,
    field_type: str,
    options: list[str],
    answers: dict[str, str],
) -> list[dict[str, str]]:
    """Build the chat messages that ask the model to match or derive an answer."""
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


def _source_summary(keys: list[str], store: dict[str, str]) -> str:
    """Render the cited sources for the status line, e.g. ``'city': 'Sydney'``."""
    return ", ".join(f"'{key}': '{store[key]}'" for key in keys if key in store)


def parse_reasoning_reply(
    text: str,
    question: str,
    answers: dict[str, str],
) -> QuestionDecision:
    """Turn the model's reply into a :class:`QuestionDecision` with provenance.

    A copied answer is resolved from the store by its cited key, so the model can
    never paraphrase a stored value into something else. A derived answer is kept
    only when it cites at least one key that exists in the store; anything else is
    returned as unknown.
    """
    unknown = QuestionDecision(question=question)
    match = _JSON_OBJECT_RE.search(text or "")
    if match is None:
        return unknown
    try:
        payload = json.loads(match.group(0))
    except (ValueError, TypeError):
        return unknown
    if not isinstance(payload, dict):
        return unknown

    category = str(payload.get("category") or "").strip()
    rationale = str(payload.get("rationale") or "").strip()
    answer = str(payload.get("answer") or "").strip()

    raw_keys = payload.get("source_keys")
    if isinstance(raw_keys, str):
        raw_keys = [raw_keys]
    keys: list[str] = []
    for raw in raw_keys or []:
        key = normalize_question(str(raw))
        if key and key in answers and key not in keys:
            keys.append(key)
    if not answer or not keys:
        return unknown  # no provenance means no answer

    answer_norm = normalize_question(answer)
    for key in keys:
        # A copy: the model returned the stored value, or echoed the stored key
        # itself. Either way resolve the exact stored value, not the wording.
        if answer_norm == normalize_question(answers[key]) or answer_norm == key:
            return QuestionDecision(
                question=question,
                category=category,
                answer=answers[key],
                matched_key=key,
                rationale=rationale,
                source_keys=[key],
                derived=False,
                source_summary=_source_summary([key], answers),
            )
    return QuestionDecision(
        question=question,
        category=category,
        answer=answer,
        rationale=rationale,
        source_keys=keys,
        derived=True,
        source_summary=_source_summary(keys, answers),
    )


def _yesno_meaning(value: str) -> str | None:
    """``"yes"`` / ``"no"`` for a yes-or-no value, otherwise ``None``."""
    text = normalize_question(value)
    if text in _YES_SYNONYMS or text in {"1", "1.0"}:
        return "yes"
    if text in _NO_SYNONYMS or text in {"0", "0.0"}:
        return "no"
    return None


def _as_number(value: str) -> float | None:
    """The first number in ``value`` (e.g. ``"5"`` or ``"4 years"`` → ``5``/``4``)."""
    match = _NUMBER_RE.search(value or "")
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:  # pragma: no cover - the regex only yields parseable text
        return None


def _derive_entailed(answer: str, keys: list[str], store: dict[str, str]) -> bool:
    """True when the cited stored values actually entail the derived ``answer``.

    The guard that keeps the "never invent" promise. A yes/no derive is only
    accepted when every cited *numeric* value agrees with it (positive ⇒ "Yes",
    zero ⇒ "No"), so a positive years-of-experience entry can imply "Yes" for an
    experience question. A non yes/no derive must be grounded in the text of a
    cited value. Anything else — including a yes/no derive that leans on a
    non-numeric entry like a different question's "No" — is rejected, because a
    wrong auto-answer is worse than asking the human.
    """
    values = [store[key] for key in keys]
    meaning = _yesno_meaning(answer)
    if meaning is not None:
        numbers = [
            number for number in (_as_number(value) for value in values) if number is not None
        ]
        if not numbers:
            return False
        if meaning == "yes":
            return all(number > 0 for number in numbers)
        return all(number == 0 for number in numbers)
    wanted = normalize_question(answer)
    return bool(wanted) and any(wanted in normalize_question(value) for value in values)


def _map_to_option(answer: str, options: list[str]) -> str | None:
    """Resolve ``answer`` to one of ``options`` (text match, then yes/no meaning)."""
    for option in options:
        if answers_match(option, answer):
            return option
    meaning = _yesno_meaning(answer)
    if meaning is not None:
        for option in options:
            if _yesno_meaning(option) == meaning:
                return option
    return None


def validate_decision(
    decision: QuestionDecision,
    store: dict[str, str],
    options: list[str] | None = None,
) -> QuestionDecision:
    """Return ``decision`` only when it is grounded and fits the field.

    A pure guard: an answer with no existing cited source, a derive the cited
    values do not entail, or a choice answer that maps to none of ``options`` all
    become *unknown* so Task 5 asks the human. A stored entry for the question
    itself always wins, so a human-confirmed ``answers.json`` value is never
    overridden by a derived one.
    """
    options = options or []
    answer = (decision.answer or "").strip()
    if not answer:
        return QuestionDecision(question=decision.question)

    keys = [key for key in decision.source_keys if key in store]
    if not keys:
        return QuestionDecision(question=decision.question)  # no provenance, no fill

    own_key = normalize_question(decision.question)
    if own_key in store:
        return QuestionDecision(
            question=decision.question,
            category=decision.category,
            answer=store[own_key],
            matched_key=own_key,
            rationale=decision.rationale,
            source_keys=[own_key],
            derived=False,
            source_summary=_source_summary([own_key], store),
        )

    if decision.derived:
        if len(answer) > _MAX_DERIVED_TEXT or not _derive_entailed(answer, keys, store):
            return QuestionDecision(question=decision.question)

    if options:
        mapped = _map_to_option(answer, options)
        if mapped is None:
            return QuestionDecision(question=decision.question)
        answer = mapped

    return decision.model_copy(
        update={
            "answer": answer,
            "source_keys": keys,
            "source_summary": _source_summary(keys, store),
        }
    )


def _cached_decision(question: str, cached: DerivedAnswer) -> QuestionDecision:
    """Turn a cached derived answer back into a decision for :func:`validate_decision`."""
    return QuestionDecision(
        question=question,
        answer=cached.answer,
        rationale=cached.rationale,
        source_keys=list(cached.source_keys),
        derived=True,
    )


class ReasoningAnswerChooser:
    """An :data:`~src.tools.llm_answers.AnswerChooser` that may match *or* derive.

    It consults the derived-answer cache first (Task 10.3), then the LLM. Every
    answer it returns has passed :func:`validate_decision`, so it is always
    grounded in the store; when nothing is grounded it returns an unknown
    decision and the question goes to Task 5.
    """

    def __init__(
        self,
        settings: LLMSettings,
        answers: dict[str, str],
        cache_path=None,
    ) -> None:
        self._settings = settings
        self._answers = answers  # live reference: Task 5 writes into it
        self._cache_path = cache_path
        self._cache: dict[str, DerivedAnswer] | None = None
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

    def _cache_or_load(self) -> dict[str, DerivedAnswer]:
        if self._cache is None:
            self._cache = (
                load_derived_answers(self._cache_path) if self._cache_path else {}
            )
        return self._cache

    async def __call__(
        self, question: str, field_type: str, options: list[str]
    ) -> QuestionDecision:
        """Answer ``question`` from the store by matching or deriving (Task 10)."""
        if not self._answers:
            return QuestionDecision(question=question)

        cached = self._cache_or_load().get(normalize_question(question))
        if cached is not None and supported_by_store(cached, self._answers):
            decision = validate_decision(
                _cached_decision(question, cached), self._answers, options
            )
            if decision.decided:
                return decision  # instant: no second LLM call

        messages = build_reasoning_messages(question, field_type, options, self._answers)
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

        decision = validate_decision(
            parse_reasoning_reply(text, question, self._answers), self._answers, options
        )
        if decision.decided and decision.derived:
            self._remember(question, decision)
        return decision

    def _remember(self, question: str, decision: QuestionDecision) -> None:
        """Cache an accepted derived answer (best-effort; never fails the run)."""
        if not self._cache_path:
            return
        snapshot = {
            key: self._answers[key]
            for key in decision.source_keys
            if key in self._answers
        }
        key = save_derived_answer(
            self._cache_path,
            question,
            decision.answer or "",
            decision.source_keys,
            snapshot,
            decision.rationale,
        )
        if not key:
            return
        self._cache_or_load()[key] = DerivedAnswer(
            answer=decision.answer or "",
            source_keys=list(decision.source_keys),
            source_snapshot=snapshot,
            rationale=decision.rationale,
        )


def build_reasoning_answer_chooser(
    settings: Settings,
    answers: dict[str, str],
    cache_path=None,
) -> ReasoningAnswerChooser | None:
    """Return the reasoning chooser, or ``None`` when no model is configured."""
    if not settings.llm.configured:
        return None
    return ReasoningAnswerChooser(
        settings.llm, answers, cache_path or settings.derived_answers_file
    )


__all__ = [
    "ReasoningAnswerChooser",
    "build_reasoning_answer_chooser",
    "build_reasoning_messages",
    "parse_reasoning_reply",
    "validate_decision",
]
