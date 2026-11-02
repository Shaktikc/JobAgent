"""Task 21: an unstarred question must never reach answering or persistence."""

from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task5Outcome
from src.tools.linkedin_easy_apply_fill.field_filling import _fill_step
from src.tools.linkedin_easy_apply_fill.required_only import only_required_fields
from src.tools.llm_answers import QuestionDecision


@pytest.mark.parametrize("kind", ["input", "textarea", "select", "radio", "checkbox"])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("remembered", [False, True])
async def test_metadata_only_required_is_untouched_before_any_answer_work(
    tmp_path, kind, existing, remembered
):
    fields = [{
        "marker": "optional", "kind": kind, "type": kind, "name": "shared",
        "question": "Any additional details?", "required": True,
        "value": "Existing answer" if existing else "", "checked": existing,
        "option": "Existing answer", "options": [{"text": "Existing answer", "value": "x"}],
    }]
    before = deepcopy(fields)
    page, chooser, ask = Mock(), AsyncMock(), AsyncMock()
    chooser.return_value = QuestionDecision(
        question=fields[0]["question"], answer="Remembered answer" if remembered else None,
    )
    ask.return_value = None
    answers = {"any additional details": "Remembered answer"}
    human = Task5Outcome()
    settings = Settings(data_dir=tmp_path, session=SessionSettings(pace_seconds=0))

    result = await _fill_step(
        page, fields, answers, settings, chooser=chooser, ask=ask, human=human,
    )

    assert result == (0, 0, [], [])
    chooser.assert_not_awaited()
    ask.assert_not_awaited()
    assert page.mock_calls == []
    assert fields == before
    assert answers == {"any additional details": "Remembered answer"}
    assert human.asked == human.answered == human.timed_out == 0
    assert not settings.answers_file.exists()


@pytest.mark.parametrize("kind", ["radio", "checkbox"])
def test_shared_choice_name_cannot_inherit_another_questions_asterisk(kind):
    fields = [
        {"marker": "required", "kind": kind, "name": "shared", "question": "Required? *"},
        {"marker": "optional", "kind": kind, "name": "shared", "question": "Optional?",
         "required": True},
    ]
    assert [field["marker"] for field in only_required_fields(fields)] == ["required"]


def test_starred_label_sets_required_for_downstream_blocking_without_mutating_input():
    fields = [{"marker": "required", "kind": "input", "question": "Availability *",
               "required": False}]
    kept = only_required_fields(fields)
    assert kept[0]["required"] is True
    assert fields[0]["required"] is False
