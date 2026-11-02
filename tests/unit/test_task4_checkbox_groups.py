"""Task 4/5 regression: a checkbox question is answered as one *group* (BUG-035).

LinkedIn renders "select all that apply" as several ``[role="checkbox"]`` options
sharing one question. The fill used to enumerate each option as its own question:
the group's question was lost, Task 5's watcher was scoped to a single option (so
ticking any other option was never captured and nothing was saved), and a stored
answer could not tick a box.

These tests are offline: they drive :func:`_fill_step` and
:func:`fill_checkbox_group` with a fake page. The DOM side (reading the group
question out of the live markup) is verified in a real browser.
"""

from __future__ import annotations

import json

from src.configuration import SessionSettings, Settings
from src.state import Task5Outcome
from src.tools.answers import normalize_question
from src.tools.linkedin_easy_apply_fill.checkbox_groups import (
    READ_GROUP_TICKS_JS,
    fill_checkbox_group,
    group_counts,
    group_key,
    read_ticked_options,
    selected_options,
    selects_option,
)
from src.tools.linkedin_easy_apply_fill.field_filling import _fill_step
from src.tools.llm_answers import QuestionDecision

_QUESTION = "Before you applied, where did you first encounter Propeller?*"
_OPTIONS = ["LinkedIn Job Ad", "LinkedIn Social Post", "Glassdoor", "YouTube"]


class _FakeElement:
    def __init__(self, label: str = "") -> None:
        self.label = label
        self.checked = False
        self.check_calls = 0

    async def evaluate(self, js: str, *args):
        return self.label

    async def check(self) -> None:
        self.checked = True
        self.check_calls += 1

    async def click(self) -> None:
        self.checked = not self.checked


class _FakePage:
    """A fake form page: ``ticked`` is the live checkbox state (option labels)."""

    def __init__(self, elements: dict[str, _FakeElement], ticked: list[str] | None = None) -> None:
        self.elements = elements
        self.ticked = list(ticked or [])

    async def get_elements_by_css_selector(self, selector: str) -> list:
        return [el for marker, el in self.elements.items() if f'"{marker}"' in selector]

    async def evaluate(self, js: str, *args):
        if js == READ_GROUP_TICKS_JS:
            return json.dumps({"selected": list(self.ticked)})
        return ""


def _settings(tmp_path, **session) -> Settings:
    session.setdefault("headless", True)
    session.setdefault("post_click_wait_seconds", 0.0)
    session.setdefault("ask_human", True)
    return Settings(session=SessionSettings(**session), data_dir=tmp_path / "data")


def _fields() -> list[dict]:
    return [
        {
            "kind": "checkbox",
            "name": "checkbox-group-_r_c2_",
            "question": _QUESTION,
            "option": option,
            "marker": f"c{index}",
            "checked": False,
            "required": True,
        }
        for index, option in enumerate(_OPTIONS)
    ]


def _unknown_chooser():
    async def choose(question, field_type, options):
        return QuestionDecision(question=question)

    return choose


def _store_chooser(value: str):
    async def choose(question, field_type, options):
        return QuestionDecision(question=question, answer=value, matched_key="stored")

    return choose


# --- Matching an answer to a group's options --------------------------------
def test_selected_options_splits_a_multi_select_answer() -> None:
    assert selected_options("Glassdoor", _OPTIONS) == ["Glassdoor"]
    assert selected_options("Glassdoor, YouTube", _OPTIONS) == ["Glassdoor", "YouTube"]
    assert selected_options("nothing here", _OPTIONS) == []


def test_selected_options_reads_yes_no_only_for_a_single_option() -> None:
    assert selected_options("Yes", ["I agree"]) == ["I agree"]
    assert selected_options("No", ["I agree"]) == []
    # "Yes" can never select every box of a multi-select question.
    assert selected_options("Yes", _OPTIONS) == []


def test_selects_option_matches_a_label_or_yes() -> None:
    assert selects_option("Glassdoor", "Glassdoor") is True
    assert selects_option("Yes", "I agree") is True
    assert selects_option("No", "I agree") is False
    assert selects_option("", "Glassdoor") is False


# --- Reading the group's ticks ----------------------------------------------
async def test_read_ticked_options_returns_every_tick(tmp_path) -> None:
    page = _FakePage({}, ticked=["Glassdoor", "YouTube"])
    assert await read_ticked_options(page, ["c0", "c2", "c3"]) == ["Glassdoor", "YouTube"]


async def test_read_ticked_options_returns_empty_without_waiting() -> None:
    page = _FakePage({}, ticked=[])
    assert await read_ticked_options(page, ["c0", "c1"], max_seconds=30.0) == []


# --- Applying one group -----------------------------------------------------
async def test_fill_checkbox_group_keeps_and_remembers_the_humans_tick(tmp_path) -> None:
    """The human's tick is saved and never toggled off by the agent."""
    page = _FakePage({f"c{i}": _FakeElement(option) for i, option in enumerate(_OPTIONS)})
    answers: dict[str, str] = {}

    async def ask(question, field):
        assert question == _QUESTION
        assert field["markers"] == ["c0", "c1", "c2", "c3"]  # every option is watched
        page.ticked = ["Glassdoor"]  # the human ticks this option
        return "Glassdoor"

    record, known, filled, unknown = await fill_checkbox_group(
        page, _fields(), _QUESTION, "checkbox-group-_r_c2_",
        settings=_settings(tmp_path), answers=answers, ask=ask,
        human=Task5Outcome(), decide=_unknown_chooser(),
        tick=lambda option_field: _tick(page, option_field),
    )

    assert (known, filled, unknown) == (True, True, False)
    assert record.value == "Glassdoor" and record.answered_by == "human"
    assert answers[normalize_question(_QUESTION)] == "Glassdoor"
    # No option was clicked: the human's own tick was left alone.
    assert all(el.check_calls == 0 for el in page.elements.values())


async def test_fill_checkbox_group_ticks_a_stored_answer(tmp_path) -> None:
    elements = {f"c{i}": _FakeElement(option) for i, option in enumerate(_OPTIONS)}
    page = _FakePage(elements)
    answers = {normalize_question(_QUESTION): "Glassdoor, LinkedIn Job Ad"}

    record, known, filled, unknown = await fill_checkbox_group(
        page, _fields(), _QUESTION, "checkbox-group-_r_c2_",
        settings=_settings(tmp_path), answers=answers, ask=None,
        human=Task5Outcome(), decide=_store_chooser(answers[normalize_question(_QUESTION)]),
        tick=lambda option_field: _tick(page, option_field),
    )

    assert (known, filled, unknown) == (True, True, False)
    assert record.value == "LinkedIn Job Ad, Glassdoor"
    assert elements["c0"].checked is True and elements["c2"].checked is True
    assert elements["c1"].checked is False and elements["c3"].checked is False


async def test_fill_checkbox_group_remembers_a_pre_ticked_selection(tmp_path) -> None:
    fields = _fields()
    fields[3]["checked"] = True  # the human ticked it before the agent got there
    answers: dict[str, str] = {}

    record, known, filled, unknown = await fill_checkbox_group(
        _FakePage({}), fields, _QUESTION, "checkbox-group-_r_c2_",
        settings=_settings(tmp_path), answers=answers, ask=None,
        human=Task5Outcome(), decide=None, tick=None,
    )

    assert (known, filled, unknown) == (True, True, False)
    assert record.value == "YouTube" and record.answered_by == "form"
    assert answers[normalize_question(_QUESTION)] == "YouTube"


async def test_fill_checkbox_group_leaves_an_unmatched_answer_unknown(tmp_path) -> None:
    record, known, filled, unknown = await fill_checkbox_group(
        _FakePage({}), _fields(), _QUESTION, "checkbox-group-_r_c2_",
        settings=_settings(tmp_path), answers={}, ask=None,
        human=Task5Outcome(), decide=_store_chooser("something else"), tick=None,
    )

    assert (known, filled, unknown) == (False, False, True)
    assert record.error == "no option matched the answer"


async def _tick(page, option_field) -> tuple[bool, str]:
    element = await page.get_elements_by_css_selector(
        f'[data-autojob-fill="{option_field["marker"]}"]'
    )
    if not element:
        return False, "field element not found"
    await element[0].check()
    return True, ""


# --- The fill path: one question, not one per option (the reported bug) -----
def test_group_key_prefers_the_shared_name_then_the_question() -> None:
    shared_name = _fields()  # every option carries the group's name
    assert group_key(shared_name[0], group_counts(shared_name)) == "name:checkbox-group-_r_c2_"

    # Per-option names: only the question is shared, and it must still group them.
    per_option = [
        {**field, "name": f"cb{index}"} for index, field in enumerate(_fields())
    ]
    assert group_key(per_option[3], group_counts(per_option)) == f"question:{_QUESTION}"

    lone = [{"kind": "checkbox", "name": "cb0", "question": "", "marker": "c0"}]
    assert group_key(lone[0], group_counts(lone)) == "field:c0"


async def test_fill_step_groups_options_that_only_share_the_question(tmp_path) -> None:
    """A group whose options have per-option names is still one question."""
    fields = [{**field, "name": f"cb{index}"} for index, field in enumerate(_fields())]
    page = _FakePage({f"c{i}": _FakeElement(option) for i, option in enumerate(_OPTIONS)})
    calls: list[str] = []

    async def ask(question, field):
        calls.append(question)
        page.ticked = ["YouTube"]
        return "YouTube"

    known, filled, unknown, records = await _fill_step(
        page, fields, {}, _settings(tmp_path), ask=ask,
        human=Task5Outcome(), chooser=_unknown_chooser(),
    )

    assert calls == [_QUESTION]
    assert (known, filled, unknown) == (1, 1, [])
    assert records[0].value == "YouTube"


async def test_fill_step_asks_once_for_the_whole_checkbox_group(tmp_path) -> None:
    page = _FakePage({f"c{i}": _FakeElement(option) for i, option in enumerate(_OPTIONS)})
    answers: dict[str, str] = {}
    calls: list[tuple[str, dict]] = []

    async def ask(question, field):
        calls.append((question, field))
        page.ticked = ["Glassdoor"]
        return "Glassdoor"

    known, filled, unknown, records = await _fill_step(
        page, _fields(), answers, _settings(tmp_path), ask=ask,
        human=Task5Outcome(), chooser=_unknown_chooser(),
    )

    # One question for all four options (the bug asked the option text, four times).
    assert [question for question, _field in calls] == [_QUESTION]
    assert calls[0][1]["options"] == _OPTIONS
    assert (known, filled, unknown) == (1, 1, [])
    assert len(records) == 1
    assert records[0].field_type == "checkbox" and records[0].value == "Glassdoor"
    assert answers[normalize_question(_QUESTION)] == "Glassdoor"


async def test_fill_step_applies_a_stored_multi_select_answer(tmp_path) -> None:
    elements = {f"c{i}": _FakeElement(option) for i, option in enumerate(_OPTIONS)}
    page = _FakePage(elements)
    answers = {normalize_question(_QUESTION): "LinkedIn Social Post, YouTube"}

    known, filled, unknown, records = await _fill_step(
        page, _fields(), answers, _settings(tmp_path), ask=None,
        human=Task5Outcome(), chooser=_store_chooser(answers[normalize_question(_QUESTION)]),
    )

    assert (known, filled, unknown) == (1, 1, [])
    assert records[0].value == "LinkedIn Social Post, YouTube"
    assert elements["c1"].checked is True and elements["c3"].checked is True
    assert elements["c0"].checked is False and elements["c2"].checked is False


# --- A stale radio marker (BUG-057) -----------------------------------------
class _StaleRadioPage(_FakePage):
    """A page whose radio fill marker is stale until re-resolved by name (BUG-057)."""

    def __init__(self, group_name: str) -> None:
        super().__init__({})
        self.group_name = group_name
        self.remark_calls: list[tuple] = []
        self.option = _FakeElement("Yes")

    async def evaluate(self, js: str, *args):
        if "groupName" in js:  # REMARK_RADIO_BY_NAME_JS
            self.remark_calls.append(tuple(args))
            name, _answer, marker = args
            if name == self.group_name:
                self.elements[str(marker)] = self.option
                return json.dumps({"ok": True})
            return json.dumps({"ok": False})
        return await super().evaluate(js, *args)


async def test_fill_step_re_resolves_a_stale_radio_marker_by_name(tmp_path) -> None:
    """BUG-057: an LLM-answered radio is filled even when its marker went stale.

    React can re-render the marked radio wrapper away while the LLM is choosing an
    answer, so the cached ``data-autojob-fill`` marker no longer resolves. The
    group's native ``name`` survives, so the fill re-resolves it by name and fills
    the matching option instead of reporting ``field element not found``.
    """
    question = "Have you implemented and integrated conversational AI platforms? *"
    fields = [
        {
            "kind": "radio",
            "type": "radio",
            "name": "radio-group-_r_kd_",
            "question": question,
            "option": option,
            "marker": f"f{index}",
            "checked": False,
            "required": True,
        }
        for index, option in enumerate(("Yes", "No"))
    ]
    page = _StaleRadioPage("radio-group-_r_kd_")

    known, filled, unknown, records = await _fill_step(
        page, fields, {}, _settings(tmp_path, ask_human=False), ask=None,
        human=Task5Outcome(), chooser=_store_chooser("Yes"),
    )

    assert (known, filled, unknown) == (1, 1, [])
    assert page.remark_calls == [("radio-group-_r_kd_", "Yes", "f0")]
    assert page.option.checked is True
    record = records[0]
    assert record.filled is True and record.error == ""
    assert record.answered_by == "llm"
