"""Unit tests for Task 4.1's LLM answer chooser (no network)."""

from __future__ import annotations

from src.configuration import LLMSettings, Settings
from src.tools.llm_answers import (
    LLMAnswerChooser,
    build_answer_chooser,
    build_messages,
    parse_decision,
)

_ANSWERS = {"city": "Sydney", "notice period": "4 weeks"}


def test_build_messages_includes_question_options_and_store() -> None:
    messages = build_messages("Preferred contact method", "select", ["Email", "Phone"], _ANSWERS)
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    user = messages[1]["content"]
    assert "Preferred contact method" in user
    assert "select" in user
    assert "Email, Phone" in user
    assert "Sydney" in user and "4 weeks" in user


def test_parse_decision_resolves_a_stored_answer() -> None:
    decision = parse_decision(
        '{"category": "location", "matched_key": "City", "rationale": "same as city"}',
        "Where do you live?",
        _ANSWERS,
    )
    assert decision.decided is True
    assert decision.answer == "Sydney"
    assert decision.matched_key == "city"
    assert decision.category == "location"
    assert decision.rationale == "same as city"


def test_parse_decision_never_invents_an_answer() -> None:
    # A key that is not in the store (or a made-up answer) is rejected outright.
    unknown = parse_decision(
        '{"category": "salary", "matched_key": "salary", "rationale": "guess"}',
        "Expected salary?",
        _ANSWERS,
    )
    assert unknown.decided is False
    assert unknown.answer is None

    empty = parse_decision('{"category": "", "matched_key": "", "rationale": ""}', "Q", _ANSWERS)
    assert empty.decided is False


def test_parse_decision_survives_prose_and_fences() -> None:
    text = 'Sure!\n```json\n{"category": "notice", "matched_key": "notice period"}\n```'
    decision = parse_decision(text, "Notice period?", _ANSWERS)
    assert decision.answer == "4 weeks"


def test_parse_decision_handles_bad_json() -> None:
    assert parse_decision("not json at all", "Q", _ANSWERS).decided is False
    assert parse_decision('{"unterminated": ', "Q", _ANSWERS).decided is False
    assert parse_decision("", "Q", _ANSWERS).decided is False


def test_build_answer_chooser_requires_configuration() -> None:
    assert build_answer_chooser(Settings(), {}) is None
    assert build_answer_chooser(Settings(llm=LLMSettings(api_key="k")), {}) is None
    chooser = build_answer_chooser(Settings(llm=LLMSettings(api_key="k", model="m")), {})
    assert chooser is not None


def test_select_only_decision_has_no_task10_provenance() -> None:
    """Task 10 extended ``QuestionDecision`` additively: the Task 4.1 chooser's
    decisions carry no derived/source provenance, so its behaviour is unchanged."""
    from src.tools.llm_answers import QuestionDecision

    decision = QuestionDecision(question="Q", answer="A", matched_key="k")
    assert decision.source_keys == []
    assert decision.derived is False
    assert decision.source_summary == ""


class _FakeClient:
    """A minimal stand-in for ``AsyncOpenAI`` that records the call."""

    def __init__(self, content: str = "", *, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.calls: list[dict] = []
        self.chat = self
        self.completions = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return _FakeResponse(self.content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


async def test_chooser_returns_the_stored_answer() -> None:
    chooser = LLMAnswerChooser(LLMSettings(api_key="k", model="m"), dict(_ANSWERS))
    fake = _FakeClient('{"category": "location", "matched_key": "city", "rationale": "r"}')
    chooser._client = fake

    decision = await chooser("Which city are you in?", "text", [])

    assert decision.answer == "Sydney"
    assert fake.calls[0]["model"] == "m"


async def test_chooser_treats_an_error_as_unknown() -> None:
    chooser = LLMAnswerChooser(LLMSettings(api_key="k", model="m"), dict(_ANSWERS))
    chooser._client = _FakeClient(error=RuntimeError("boom"))

    assert (await chooser("Which city?", "text", [])).decided is False


async def test_chooser_skips_the_call_when_the_store_is_empty() -> None:
    chooser = LLMAnswerChooser(LLMSettings(api_key="k", model="m"), {})
    fake = _FakeClient('{"matched_key": "city"}')
    chooser._client = fake

    assert (await chooser("Which city?", "text", [])).decided is False
    assert fake.calls == []


class _RecordingStatus:
    """A minimal Task 9 status object that records what it is told."""

    def __init__(self) -> None:
        self.llm_lines: list[str] = []

    def llm(self, action: str, detail: str = "") -> None:
        self.llm_lines.append(f"LLM: {action}" + (f" - {detail}" if detail else ""))


async def test_decide_announces_the_question_and_the_decision() -> None:
    """Task 9: before the LLM call the panel says what it is classifying, and
    after it says the chosen answer (Task 4.1)."""
    from src.tools.linkedin_easy_apply_fill.field_filling import _decide
    from src.tools.llm_answers import QuestionDecision

    status = _RecordingStatus()

    async def chooser(question, field_type, options):
        return QuestionDecision(
            question=question,
            category="location",
            matched_key="city",
            answer="Sydney",
            rationale="same as city",
        )

    decision = await _decide(chooser, "Which city are you in?", "text", [], status)

    assert decision.answer == "Sydney"
    assert any("classifying the question" in line for line in status.llm_lines)
    assert any("answered" in line and "Sydney" in line for line in status.llm_lines)


async def test_decide_says_when_it_has_no_confident_answer() -> None:
    from src.tools.linkedin_easy_apply_fill.field_filling import _decide
    from src.tools.llm_answers import QuestionDecision

    status = _RecordingStatus()

    async def chooser(question, field_type, options):
        return QuestionDecision(question=question)

    decision = await _decide(chooser, "Expected salary?", "text", [], status)

    assert decision.decided is False
    assert any("no confident answer" in line for line in status.llm_lines)
