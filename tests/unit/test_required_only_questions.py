"""Regression tests: answer only questions marked required (``*``).

LinkedIn Easy Apply adds optional diversity/screening questions (ethnicity,
gender, veteran status, ...). They do not block submission, so the fill must drop
them untouched instead of pausing on them for the human or filling a stored
answer. Only questions whose label carries LinkedIn's ``*`` marker are answered.
"""

from __future__ import annotations

from src.configuration import SessionSettings, Settings
from src.state import Task5Outcome
from src.tools.linkedin_easy_apply_fill.field_filling import _fill_step
from src.tools.linkedin_easy_apply_fill.required_only import (
    has_required_marker,
    is_required_field,
    only_required_fields,
)
from src.tools.llm_answers import QuestionDecision


def _field(
    marker: str,
    question: str,
    *,
    kind: str = "input",
    name: str = "",
    option: str = "",
    required: bool = False,
    checked: bool = False,
) -> dict:
    return {
        "marker": marker,
        "kind": kind,
        "type": kind,
        "name": name or marker,
        "question": question,
        "option": option,
        "required": required,
        "checked": checked,
        "value": "",
        "options": [],
    }


# --- The marker rule ---------------------------------------------------------
def test_has_required_marker_reads_the_visible_asterisk() -> None:
    assert has_required_marker("What is your current availability / notice period?*") is True
    assert has_required_marker("Are you eligible to work in this country? * ") is True
    assert has_required_marker("I identify my ethnicity as:") is False
    assert has_required_marker("") is False
    assert has_required_marker(None) is False


def test_is_required_field_uses_only_the_visible_marker() -> None:
    assert is_required_field(_field("f0", "Phone number", required=True)) is False
    # Some layouts only put the marker in the label; the text still wins.
    assert is_required_field(_field("f5", "Notice period?*")) is True
    assert is_required_field(_field("f1", "I Identify my gender as:")) is False


def test_only_required_fields_drops_optional_text_questions() -> None:
    fields = [
        _field("f0", "What is your current availability / notice period?*", required=True),
        _field("f1", "I identify my ethnicity as:"),
        _field("f2", "I am a Veteran and have served previously?"),
    ]
    kept = only_required_fields(fields)
    assert [field["marker"] for field in kept] == ["f0"]


def test_only_required_fields_keeps_a_whole_required_radio_group() -> None:
    fields = [
        _field("f0", "Do you require sponsorship?*", kind="radio", name="sponsor", option="Yes"),
        _field("f1", "Do you require sponsorship?*", kind="radio", name="sponsor", option="No"),
        _field("f2", "Gender?", kind="radio", name="gender", option="Woman"),
        _field("f3", "Gender?", kind="radio", name="gender", option="Man"),
    ]
    kept = only_required_fields(fields)
    assert [field["marker"] for field in kept] == ["f0", "f1"]


def test_only_required_fields_keeps_a_whole_required_checkbox_group() -> None:
    fields = [
        _field("c0", "Where did you first hear about us?*", kind="checkbox", name="source",
               option="LinkedIn"),
        _field("c1", "Where did you first hear about us?*", kind="checkbox", name="source",
               option="Glassdoor"),
        _field("c2", "Which benefits matter?", kind="checkbox", name="benefit", option="Health"),
        _field("c3", "Which benefits matter?", kind="checkbox", name="benefit", option="Travel"),
    ]
    kept = only_required_fields(fields)
    assert [field["marker"] for field in kept] == ["c0", "c1"]


def test_only_required_fields_uses_the_label_when_the_group_flag_is_missing() -> None:
    fields = [
        _field("c0", "Where did you first hear about us?*", kind="checkbox", name="source",
               option="LinkedIn"),
        _field("c1", "Where did you first hear about us?*", kind="checkbox", name="source",
               option="Glassdoor"),
    ]
    assert [field["marker"] for field in only_required_fields(fields)] == ["c0", "c1"]


# --- The fill path -----------------------------------------------------------
class _FakeElement:
    def __init__(self, label: str) -> None:
        self.label = label
        self.filled = None

    async def evaluate(self, js: str, *args):
        if args:
            self.filled = args[0]
        return self.label


class _FakePage:
    def __init__(self, elements: dict[str, _FakeElement]) -> None:
        self.elements = elements

    async def get_elements_by_css_selector(self, selector: str):
        return [el for marker, el in self.elements.items() if f'"{marker}"' in selector]


def _settings(tmp_path) -> Settings:
    return Settings(
        session=SessionSettings(headless=True, post_click_wait_seconds=0.0, ask_human=True),
        data_dir=tmp_path / "data",
    )


def _recorded_chooser(calls: list[str]):
    """A chooser that knows one stored answer but records every question."""

    async def choose(question: str, field_type: str, options: list[str]) -> QuestionDecision:
        calls.append(question)
        if "availability" in question.lower():
            return QuestionDecision(question=question, answer="Immediate")
        return QuestionDecision(question=question)

    return choose


async def test_fill_step_skips_an_optional_question_even_when_it_is_known(tmp_path) -> None:
    """An optional question is never asked, never filled, and never put to the LLM."""
    fields = [
        _field("f0", "What is your current availability / notice period?*", required=True),
        _field("f1", "I identify my ethnicity as:"),
    ]
    page = _FakePage({"f0": _FakeElement("availability"), "f1": _FakeElement("ethnicity")})
    chooser_calls: list[str] = []
    asked: list[str] = []

    async def ask(question: str, field: dict) -> str | None:
        asked.append(question)
        return None

    known, filled, unknown, records = await _fill_step(
        page,
        fields,
        {},
        _settings(tmp_path),
        ask=ask,
        human=Task5Outcome(),
        chooser=_recorded_chooser(chooser_calls),
    )

    assert chooser_calls == ["What is your current availability / notice period?*"]
    assert asked == []
    assert (known, filled, unknown) == (1, 1, [])
    assert page.elements["f0"].filled == "Immediate"
    assert page.elements["f1"].filled is None
    assert [record.question for record in records] == [
        "What is your current availability / notice period?*"
    ]


async def test_fill_step_skips_an_optional_question_the_human_would_have_answered(tmp_path) -> None:
    """The optional diversity question no longer pauses the run for the human."""
    fields = [
        _field("f0", "I Identify my gender as:", kind="radio", name="gender", option="Woman"),
        _field("f1", "I Identify my gender as:", kind="radio", name="gender", option="Man"),
        _field("f2", "I am a Veteran and have served previously?", kind="radio",
               name="veteran", option="Yes"),
        _field("f3", "I am a Veteran and have served previously?", kind="radio",
               name="veteran", option="No"),
    ]
    page = _FakePage(
        {
            "f0": _FakeElement("Woman"),
            "f1": _FakeElement("Man"),
            "f2": _FakeElement("Yes"),
            "f3": _FakeElement("No"),
        }
    )
    asked: list[str] = []

    async def ask(question: str, field: dict) -> str | None:
        asked.append(question)
        return "Yes"

    known, filled, unknown, records = await _fill_step(
        page, fields, {}, _settings(tmp_path), ask=ask, human=Task5Outcome(),
    )

    assert asked == []
    assert (known, filled, unknown, records) == (0, 0, [], [])
    assert all(element.filled is None for element in page.elements.values())
