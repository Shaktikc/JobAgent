"""Task 5 regression: a <select>'s prompt must never become the saved answer.

BUG-037: the answer watcher read the select's *selected option text* with no
placeholder check, so the moment the human clicked the dropdown open (the prompt
"Select an option" still selected) it recorded that prompt as their answer and
stored it in ``answers.json`` for the question. Reproduced live on LinkedIn's
"right to work" and "salary expectations" selects, whose prompt option carries
``value=""`` and prompt text. The recorded value then also leaked into the next
question's answer because the reader trusted any recorded value, not just the one
for the question being asked.

The browser-side fix lives in
:mod:`src.tools.linkedin_ask_human.answer_js` (``isSelectPrompt`` plus the scope
check) and is verified in a live browser; these tests cover the pure rules, the
store guards, and the "already answered" check that the fill step uses.
"""

from __future__ import annotations

import json

from src.configuration import Settings
from src.state import Task5Outcome
from src.tools.answers import load_answers
from src.tools.forms import is_prompt_answer, select_is_answered
from src.tools.linkedin_ask_human import (
    _looks_unlabeled,
    _remember_answer,
    _store_answer,
)
from src.tools.linkedin_easy_apply_fill.field_filling import _control_already_answered


# --- The pure select rules ---------------------------------------------------
def test_select_prompt_options_are_not_answers() -> None:
    # LinkedIn: the prompt option is disabled with value="" and this text.
    assert select_is_answered("", "Select an option") is False
    assert select_is_answered("", "Choose an option") is False
    assert select_is_answered("", "Please select") is False
    assert select_is_answered("", "select one") is False
    # Older forms give the prompt a sentinel value but keep prompt text.
    assert select_is_answered("0", "Select an option") is False
    # Nothing selected at all.
    assert select_is_answered("", "") is False


def test_real_select_choices_are_answers() -> None:
    assert (
        select_is_answered(
            "24f7d160-dd63-45b7-8acd-6b939aaecf29",
            "Full working rights - Citizenship or Permanent resident",
        )
        is True
    )
    assert select_is_answered("fbc0e5e5", "60,000-70,000") is True
    # "None" is a legitimate answer, unlike a prompt phrase.
    assert select_is_answered("uuid-none", "None") is True


def test_is_prompt_answer_recognises_prompt_phrases() -> None:
    assert is_prompt_answer("Select an option") is True
    assert is_prompt_answer("  select an option. ") is True
    assert is_prompt_answer("Choose one") is True
    assert is_prompt_answer("Please choose") is True
    # Real answers, including the legitimate "None" option.
    assert is_prompt_answer("No working rights") is False
    assert is_prompt_answer("None") is False
    assert is_prompt_answer("") is False


# --- The fill step's "already answered" check --------------------------------
def test_select_still_showing_its_prompt_is_unanswered() -> None:
    field = {"kind": "select", "value": "", "selected_text": "Select an option"}
    assert _control_already_answered(field) is False
    field = {"kind": "select", "value": "0", "selected_text": "Choose an option"}
    assert _control_already_answered(field) is False


def test_select_with_a_real_choice_is_answered() -> None:
    field = {
        "kind": "select",
        "value": "24f7d160",
        "selected_text": "Full working rights - Citizenship or Permanent resident",
    }
    assert _control_already_answered(field) is True
    # A pre-filled select without a readable option text still counts.
    assert _control_already_answered({"kind": "select", "value": "au"}) is True
    # Text controls are unchanged.
    assert _control_already_answered({"kind": "input", "value": "6"}) is True
    assert _control_already_answered({"kind": "input", "value": ""}) is False


# --- The store guards --------------------------------------------------------
def _settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


def test_store_answer_never_persists_a_prompt(tmp_path) -> None:
    settings = _settings(tmp_path)
    question = "Which of the following statements best describes your right to work?"

    _store_answer(settings, question, "Select an option", Task5Outcome())
    assert load_answers(settings.answers_file) == {}

    _store_answer(settings, question, "No working rights", Task5Outcome())
    assert load_answers(settings.answers_file) == {
        "which of the following statements best describes your right to work": "No working rights"
    }


def test_remember_answer_never_persists_a_prompt(tmp_path) -> None:
    settings = _settings(tmp_path)
    answers: dict[str, str] = {}
    human = Task5Outcome()

    _remember_answer(
        settings,
        answers,
        human,
        "What are your salary expectations (base salary)?",
        "Select an option",
    )
    assert answers == {}
    assert load_answers(settings.answers_file) == {}
    assert not human.notes or "remembered" not in human.notes

    _remember_answer(
        settings,
        answers,
        human,
        "What are your salary expectations (base salary)?",
        "50,000-60,000",
    )
    assert answers == {"what are your salary expectations (base salary)": "50,000-60,000"}
    assert json.loads(settings.answers_file.read_text(encoding="utf-8")) == answers
    assert "remembered" in (human.notes or "")


# --- The split kept the module's API ----------------------------------------
def test_split_package_reexports_its_api() -> None:
    """The package split must not break the names callers/tests import."""
    from src.tools import browser as browser_tools
    from src.tools.linkedin_ask_human import (
        _HIDE_UNKNOWN_JS,
        _READ_FORM_ANSWER_JS,
        _READ_UNKNOWN_JS,
        _SHOW_UNKNOWN_JS,
        _WATCH_FORM_ANSWER_JS,
        ask_human_for_answer,
    )

    assert _looks_unlabeled("radio-group-_r_1t_")
    assert browser_tools.ask_human_for_answer is ask_human_for_answer
    for js in (
        _WATCH_FORM_ANSWER_JS,
        _READ_FORM_ANSWER_JS,
        _SHOW_UNKNOWN_JS,
        _READ_UNKNOWN_JS,
        _HIDE_UNKNOWN_JS,
    ):
        assert "isSelectPrompt" in js or "autojob-unknown" in js
