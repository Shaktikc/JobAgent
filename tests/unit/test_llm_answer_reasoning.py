"""Unit tests for Task 10's reasoning answer chooser (no network).

Covers Subtask 10.1 (match *or* derive with provenance), Subtask 10.2 (ground and
validate a derived answer — never invent), and Subtask 10.3 (remember a derived
answer in a cache separate from the human-confirmed ``answers.json``).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from src.configuration import LLMSettings, Settings
from src.tools.derived_answers import (
    DerivedAnswer,
    load_derived_answers,
    save_derived_answer,
    supported_by_store,
)
from src.tools.llm_answer_reasoning import (
    ReasoningAnswerChooser,
    build_reasoning_answer_chooser,
    build_reasoning_messages,
    parse_reasoning_reply,
    validate_decision,
)
from src.tools.llm_answers import QuestionDecision

_AI_KEY = "how many years of work experience do you have with artificial intelligence (ai)"
_STORE = {_AI_KEY: "5", "enter city or location": "Sydney, New South Wales, Australia"}


# --- Subtask 10.1: match or derive, with provenance -------------------------
def test_build_reasoning_messages_includes_question_options_and_store() -> None:
    messages = build_reasoning_messages(
        "Preferred contact method", "select", ["Email", "Phone"], _STORE
    )
    assert messages[0]["role"] == "system"
    assert "DERIVE" in messages[0]["content"]
    user = messages[1]["content"]
    assert "Preferred contact method" in user
    assert "Email, Phone" in user
    assert "Sydney, New South Wales, Australia" in user


def test_parse_matches_a_copied_answer() -> None:
    decision = parse_reasoning_reply(
        json.dumps({"category": "location", "answer": "Sydney, New South Wales, Australia",
                    "source_keys": ["enter city or location"], "rationale": "same question"}),
        "Where do you live?",
        _STORE,
    )
    assert decision.decided is True and decision.derived is False
    assert decision.matched_key == "enter city or location"
    assert decision.answer == "Sydney, New South Wales, Australia"
    assert decision.source_keys == ["enter city or location"]
    assert "enter city or location" in decision.source_summary


def test_parse_resolves_an_echoed_key_as_a_copy() -> None:
    decision = parse_reasoning_reply(
        json.dumps({"answer": "enter city or location", "source_keys": ["enter city or location"]}),
        "City?",
        _STORE,
    )
    assert decision.derived is False
    assert decision.answer == "Sydney, New South Wales, Australia"


def test_parse_keeps_a_derived_answer_with_existing_sources() -> None:
    decision = parse_reasoning_reply(
        json.dumps({"category": "experience", "answer": "Yes", "source_keys": [_AI_KEY],
                    "rationale": "5 years of AI experience means yes"}),
        "Experience on AI?",
        _STORE,
    )
    assert decision.decided is True and decision.derived is True
    assert decision.answer == "Yes" and decision.matched_key == ""
    assert decision.source_keys == [_AI_KEY]


def test_parse_rejects_a_derive_with_no_or_unknown_sources() -> None:
    assert parse_reasoning_reply(
        '{"answer": "Yes", "source_keys": []}', "Experience on AI?", _STORE
    ).decided is False
    assert parse_reasoning_reply(
        '{"answer": "100000", "source_keys": ["expected salary"]}', "Expected salary?", _STORE
    ).decided is False


def test_parse_survives_prose_and_fences() -> None:
    body = json.dumps({"category": "exp", "answer": "Yes", "source_keys": [_AI_KEY]})
    decision = parse_reasoning_reply(f"Sure!\n```json\n{body}\n```", "Experience on AI?", _STORE)
    assert decision.derived is True and decision.answer == "Yes"


def test_parse_handles_bad_json() -> None:
    assert parse_reasoning_reply("not json", "Q", _STORE).decided is False
    assert parse_reasoning_reply('{"unterminated": ', "Q", _STORE).decided is False
    assert parse_reasoning_reply("", "Q", _STORE).decided is False


# --- Subtask 10.2: ground and validate (never invent) -----------------------
def _derived(question: str, answer: str, keys: list[str]) -> QuestionDecision:
    return QuestionDecision(question=question, answer=answer, source_keys=keys, derived=True)


def test_validate_rejects_an_empty_answer_or_no_existing_source() -> None:
    assert validate_decision(_derived("Q", "", [_AI_KEY]), _STORE, []).decided is False
    assert validate_decision(_derived("Q", "Yes", []), _STORE, []).decided is False
    assert validate_decision(_derived("Q", "Yes", ["missing key"]), _STORE, []).decided is False


def test_validate_answers_yes_no_from_positive_years() -> None:
    """The motivating case: 'Experience on AI?' → Yes from the AI years entry."""
    decision = validate_decision(
        _derived("Experience on AI?", "Yes", [_AI_KEY]), _STORE, ["Yes", "No"]
    )
    assert decision.decided is True and decision.answer == "Yes"
    assert decision.derived is True and decision.source_keys == [_AI_KEY]


def test_validate_rejects_a_choice_derive_that_maps_to_no_option() -> None:
    decision = validate_decision(
        _derived("Experience on AI?", "Definitely", [_AI_KEY]), _STORE, ["Yes", "No"]
    )
    assert decision.decided is False  # no option matched → Task 5 asks


def test_validate_rejects_a_yes_no_derive_from_a_non_numeric_source() -> None:
    # The note in task 10: reading a different "No" as "not authorised" is a
    # cross-meaning guess and must not be made.
    store = {"do you have full, unrestricted working rights in australia": "No"}
    decision = validate_decision(
        _derived("Are you authorised to work in Australia?", "No", list(store)),
        store,
        ["Yes", "No"],
    )
    assert decision.decided is False


def test_validate_rejects_a_derive_that_contradicts_its_source() -> None:
    store = {"how many years of experience do you have": "0"}
    decision = validate_decision(
        _derived("Do you have experience?", "Yes", list(store)), store, ["Yes", "No"]
    )
    assert decision.decided is False


def test_validate_rejects_a_long_derived_text() -> None:
    decision = _derived("Where do you live?", "x" * 500, ["enter city or location"])
    assert validate_decision(decision, _STORE, []).decided is False


def test_validate_keeps_a_grounded_text_derive() -> None:
    decision = _derived("Which city are you in?", "Sydney", ["enter city or location"])
    kept = validate_decision(decision, _STORE, [])
    assert kept.decided is True and kept.answer == "Sydney"


def test_validate_lets_a_human_confirmed_entry_win() -> None:
    """A stored entry for the question itself is never overridden by a derive."""
    store = {**_STORE, "experience on ai": "No"}
    decision = validate_decision(
        _derived("Experience on AI?", "Yes", [_AI_KEY]), store, ["Yes", "No"]
    )
    assert decision.answer == "No" and decision.derived is False
    assert decision.matched_key == "experience on ai"


# --- Subtask 10.3: the derived-answer cache ---------------------------------
def test_load_missing_or_corrupt_cache_is_empty(tmp_path) -> None:
    assert load_derived_answers(tmp_path / "absent.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_derived_answers(bad) == {}
    not_a_dict = tmp_path / "list.json"
    not_a_dict.write_text("[1, 2]", encoding="utf-8")
    assert load_derived_answers(not_a_dict) == {}


def test_save_and_load_round_trip(tmp_path) -> None:
    cache_file = tmp_path / "derived_answers.json"
    key = save_derived_answer(
        cache_file, "Experience on AI?", "Yes", [_AI_KEY], {_AI_KEY: "5"}, "years > 0"
    )
    assert key == "experience on ai"
    entry = load_derived_answers(cache_file)["experience on ai"]
    assert entry.answer == "Yes" and entry.source_keys == [_AI_KEY]
    assert entry.source_snapshot == {_AI_KEY: "5"} and entry.rationale == "years > 0"
    assert supported_by_store(entry, _STORE) is True


def test_supported_by_store_tracks_source_changes() -> None:
    entry = DerivedAnswer(answer="Yes", source_keys=[_AI_KEY], source_snapshot={_AI_KEY: "5"})
    assert supported_by_store(entry, _STORE) is True
    assert supported_by_store(entry, {_AI_KEY: "7"}) is False  # value changed
    assert supported_by_store(entry, {}) is False  # source disappeared
    assert supported_by_store(DerivedAnswer(answer="Yes"), _STORE) is False


# --- The chooser end to end (no network) ------------------------------------
class _FakeClient:
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
        choice = SimpleNamespace(message=SimpleNamespace(content=self.content))
        return SimpleNamespace(choices=[choice])


def _chooser(cache_file, store=None) -> ReasoningAnswerChooser:
    answers = dict(_STORE if store is None else store)
    return ReasoningAnswerChooser(LLMSettings(api_key="k", model="m"), answers, cache_file)


def test_build_reasoning_answer_chooser_requires_configuration() -> None:
    assert build_reasoning_answer_chooser(Settings(), {}) is None
    assert build_reasoning_answer_chooser(Settings(llm=LLMSettings(api_key="k")), {}) is None
    settings = Settings(llm=LLMSettings(api_key="k", model="m"))
    assert isinstance(build_reasoning_answer_chooser(settings, {}), ReasoningAnswerChooser)


async def test_chooser_derives_validates_and_caches(tmp_path) -> None:
    cache_file = tmp_path / "derived_answers.json"
    answers = dict(_STORE)
    chooser = ReasoningAnswerChooser(LLMSettings(api_key="k", model="m"), answers, cache_file)
    chooser._client = _FakeClient(
        json.dumps({"category": "experience", "answer": "Yes", "source_keys": [_AI_KEY]})
    )

    decision = await chooser("Experience on AI?", "radio", ["Yes", "No"])

    assert decision.decided is True and decision.answer == "Yes" and decision.derived is True
    # Cached for next time; the human store is untouched.
    assert load_derived_answers(cache_file)["experience on ai"].answer == "Yes"
    assert answers == _STORE


async def test_chooser_reuses_the_cache_without_an_llm_call(tmp_path) -> None:
    cache_file = tmp_path / "derived_answers.json"
    save_derived_answer(cache_file, "Experience on AI?", "Yes", [_AI_KEY], {_AI_KEY: "5"})
    chooser = _chooser(cache_file)
    chooser._client = _FakeClient(error=RuntimeError("should not be called"))

    decision = await chooser("Experience on AI?", "radio", ["Yes", "No"])

    assert decision.decided is True and decision.answer == "Yes"
    assert chooser._client.calls == []


async def test_chooser_re_derives_when_the_source_changed(tmp_path) -> None:
    cache_file = tmp_path / "derived_answers.json"
    save_derived_answer(cache_file, "Experience on AI?", "Yes", [_AI_KEY], {_AI_KEY: "0"})
    chooser = _chooser(cache_file)
    chooser._client = _FakeClient(
        json.dumps({"answer": "Yes", "source_keys": [_AI_KEY]})
    )

    decision = await chooser("Experience on AI?", "radio", ["Yes", "No"])

    assert decision.decided is True
    assert len(chooser._client.calls) == 1  # stale cache was discarded, re-derived


async def test_chooser_treats_an_error_as_unknown(tmp_path) -> None:
    chooser = _chooser(tmp_path / "c.json")
    chooser._client = _FakeClient(error=RuntimeError("boom"))
    assert (await chooser("Experience on AI?", "radio", ["Yes", "No"])).decided is False


async def test_chooser_skips_the_call_when_the_store_is_empty(tmp_path) -> None:
    chooser = _chooser(tmp_path / "c.json", store={})
    chooser._client = _FakeClient('{"answer": "Yes", "source_keys": ["x"]}')
    assert (await chooser("Experience on AI?", "radio", ["Yes", "No"])).decided is False
    assert chooser._client.calls == []


# --- Task 9 status + the fill path record provenance ------------------------
class _RecordingStatus:
    def __init__(self) -> None:
        self.llm_lines: list[str] = []

    def llm(self, action: str, detail: str = "") -> None:
        self.llm_lines.append(f"LLM: {action}" + (f" - {detail}" if detail else ""))


async def test_decide_states_the_derived_source() -> None:
    from src.tools.linkedin_easy_apply_fill.field_filling import _decide

    store = dict(_STORE)
    decision = validate_decision(
        parse_reasoning_reply(
            json.dumps({"answer": "Yes", "source_keys": [_AI_KEY], "category": "experience"}),
            "Experience on AI?",
            store,
        ),
        store,
        ["Yes", "No"],
    )
    status = _RecordingStatus()

    async def chooser(question, field_type, options):
        return decision

    result = await _decide(chooser, "Experience on AI?", "radio", ["Yes", "No"], status)

    assert result.answer == "Yes"
    assert any(
        "derived from" in line and "artificial intelligence (ai)" in line
        for line in status.llm_lines
    )


class _FakeElement:
    def __init__(self, label: str = "") -> None:
        self.label = label
        self.clicked = False

    async def evaluate(self, js: str, *args):
        return self.label

    async def click(self) -> None:
        self.clicked = True


class _FakePage:
    def __init__(self, elements: dict[str, _FakeElement]) -> None:
        self.elements = elements

    async def get_elements_by_css_selector(self, selector: str) -> list:
        return [el for marker, el in self.elements.items() if f'"{marker}"' in selector]

    async def evaluate(self, js: str, *args):
        return ""


async def test_fill_step_records_the_derived_answer_and_its_source(tmp_path) -> None:
    """The concrete case end to end: 'Experience on AI?' is filled Yes and the
    run state records that it was derived from the stored AI years entry."""
    from src.tools.linkedin_easy_apply_fill.field_filling import _fill_step

    store = dict(_STORE)

    def _radio(option: str, marker: str) -> dict:
        return {"kind": "radio", "name": "ai", "question": "Experience on AI?*",
                "option": option, "marker": marker, "required": True}

    fields = [_radio("Yes", "m1"), _radio("No", "m2")]
    page = _FakePage({"m1": _FakeElement("Yes"), "m2": _FakeElement("No")})

    async def chooser(question, field_type, options):
        return validate_decision(
            parse_reasoning_reply(
                json.dumps({"answer": "Yes", "source_keys": [_AI_KEY]}), question, store
            ),
            store,
            options,
        )

    known, filled, unknown, records = await _fill_step(
        page, fields, store, Settings(data_dir=tmp_path), chooser=chooser
    )

    assert (known, filled, unknown) == (1, 1, [])
    record = records[0]
    assert record.value == "Yes" and record.answered_by == "llm"
    assert record.derived is True and record.source_keys == [_AI_KEY]
    assert page.elements["m1"].clicked is True
