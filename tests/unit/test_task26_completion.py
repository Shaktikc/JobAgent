"""Persistence and inactivity contract for the human-answer wait loop."""

import json
from unittest.mock import Mock

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task5Outcome
from src.tools.answers import load_answers
from src.tools.linkedin_ask_human import flow, store


class Page:
    def __init__(self, samples, skip=False):
        self.samples = iter(samples)
        self.current = {}
        self.skip = skip
        self.saved = False

    async def evaluate(self, script, *args):
        if script == flow._READ_FORM_ANSWER_JS:
            self.current = next(self.samples, self.current)
            return json.dumps(self.current)
        if script == flow._READ_UNKNOWN_JS:
            return json.dumps({"state": "skipped" if self.skip else "pending"})
        if script == flow._MARK_SAVED_JS:
            self.saved = True
        return True


@pytest.mark.parametrize("finish", ["complete", "timeout", "skip"])
async def test_pending_values_only_persist_on_completion(tmp_path, monkeypatch, finish):
    settings = Settings(
        data_dir=tmp_path, session=SessionSettings(ask_timeout_seconds=1, ask_poll_seconds=0.4)
    )
    clock = [0.0]

    async def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(flow.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(flow.asyncio, "sleep", sleep)
    monkeypatch.setattr(flow, "_SAVED_VISIBLE_SECONDS", 0)
    writer = Mock(wraps=store._store_answer)
    monkeypatch.setattr(flow, "_store_answer", writer)
    samples = [{"value": "", "done": False, "activity": 0}]
    # Interaction extends beyond the original deadline without saving anything.
    samples += [{"value": "Two years"[:i], "done": False, "activity": i} for i in range(1, 9)]
    if finish == "complete":
        samples += [{"value": "Two years", "done": True, "activity": 9}]
    page = Page(samples, skip=finish == "skip")
    human = Task5Outcome()
    result = await flow.ask_human_for_answer(
        page, "Experience", "text", "", settings, lambda _: None, human, markers=["a"]
    )
    if finish == "complete":
        assert clock[0] > 1
        assert result == "Two years"
        writer.assert_called_once_with(settings, "Experience", "Two years", human)
        assert load_answers(settings.answers_file) == {"experience": "Two years"}
    else:
        assert result is None and not page.saved
        writer.assert_not_called()
        assert load_answers(settings.answers_file) == {}


def test_remember_does_not_write_completed_answer_twice(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path)
    writer = Mock(wraps=store.save_answer)
    monkeypatch.setattr(store, "save_answer", writer)
    human = Task5Outcome()
    store._store_answer(settings, "Experience", "Two years", human)
    answers = {}
    store._remember_answer(settings, answers, human, "Experience", "Two years")
    assert answers == {"experience": "Two years"}
    assert writer.call_count == 1
