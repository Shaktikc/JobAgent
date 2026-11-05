"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

import json

import pytest

from src.configuration import SessionSettings, Settings
from src.tools import linkedin_easy_apply_fill as fill_tools
from src.tools.answers import normalize_question
from src.tools.linkedin import build_jobs_search_url
from src.tools.llm_answers import QuestionDecision

from .fakes import FakeElement, FakePage

SEARCH_URL = build_jobs_search_url("software engineer")


def _filter_element(page: FakePage) -> FakeElement:
    """An Easy Apply filter control that flips the page's filter state when clicked."""

    def _click() -> None:
        page.filter_selected = True

    return FakeElement("Easy Apply filter.", on_click=_click)


# Real class strings captured from the live LinkedIn results page (see
# test_find_easy_apply_filter_from_real_linkedin_dom).
_FILTER_PILL_CLASS = (
    "artdeco-pill artdeco-pill--slate artdeco-pill--2 artdeco-pill--choice ember-view "
    "search-reusables__filter-pill-button"
)
_APPLY_BUTTON_CLASS = (
    "jobs-apply-button artdeco-button artdeco-button--3 artdeco-button--primary ember-view"
)


def _job_card(page: FakePage, index: int, title: str) -> FakeElement:
    """A job card that selects its details pane when clicked."""

    def _select() -> None:
        page.selected_job = index

    return FakeElement(title, on_click=_select)


def _settings(tmp_path, **session) -> Settings:
    # Task 5's browser prompt is off by default in tests; Task 5 tests enable it.
    session.setdefault("ask_human", False)
    # Task 1's optional AI-button wait is skipped by default so tests stay fast.
    session.setdefault("ai_search_timeout_seconds", 0)
    # The post-click settle is a real-time pacing delay; unit tests drive fake
    # pages that are already loaded, so skip it unless a test sets it.
    session.setdefault("post_click_wait_seconds", 0)
    # At the terminal step the browser is left open for the human; keep the wait
    # short in tests so the run still closes the session and finishes quickly.
    session.setdefault("keep_open_timeout_seconds", 0.05)
    session.setdefault("keep_open_poll_seconds", 0.01)
    return Settings(session=SessionSettings(**session), data_dir=tmp_path)


def _text_field(marker: str, name: str, question: str, *, required: bool = False) -> dict:
    return {
        "marker": marker,
        "kind": "input",
        "type": "text",
        "name": name,
        "question": question + " *" if required else question,
        "option": "",
        "required": required,
        "checked": False,
        "value": "",
        "options": [],
    }


def _contact_step_fields() -> list[dict]:
    """A required Contact-info step: email select, country select, phone input."""
    return [
        {
            "marker": "f0",
            "kind": "select",
            "type": "select",
            "name": "email",
            "question": "Email address *",
            "option": "",
            "required": True,
            "checked": False,
            "value": "",
            "options": [{"value": "me@example.com", "text": "me@example.com"}],
        },
        {
            "marker": "f1",
            "kind": "select",
            "type": "select",
            "name": "country",
            "question": "Phone country code *",
            "option": "",
            "required": True,
            "checked": False,
            "value": "",
            "options": [{"value": "Australia (+61)", "text": "Australia (+61)"}],
        },
        _text_field("f2", "phone", "Mobile phone number", required=True),
    ]


def _radio_field(
    marker: str, name: str, question: str, option: str, *, required: bool = False
) -> dict:
    return {
        "marker": marker,
        "kind": "radio",
        "type": "radio",
        "name": name,
        "question": question + " *" if required else question,
        "option": option,
        "required": required,
        "checked": False,
        "value": "",
        "options": [],
    }


def _human_asker(
    monkeypatch: pytest.MonkeyPatch,
    answer: str | None,
    calls: list[str],
) -> None:
    """Patch the Task 5 browser prompt with a canned answer (None = skip)."""

    async def fake_ask(page, question, field_type, hint, settings, notify, task5=None, **kwargs):
        calls.append(question)
        if task5 is not None:
            task5.asked += 1
            if answer is None:
                task5.skipped += 1
            else:
                task5.answered += 1
                if question not in task5.answered_questions:
                    task5.answered_questions.append(question)
        return answer

    monkeypatch.setattr(fill_tools.form_walk.core, "ask_human_for_answer", fake_ask)


def _store_chooser(answers: dict[str, str]):
    """Stand in for the Task 4.1 LLM: choose the stored answer that fits.

    It reads ``answers`` live, so an answer Task 5 just remembered is reused on
    the next step exactly as the real model would reuse it.
    """

    async def choose(question: str, field_type: str, options: list[str]) -> QuestionDecision:
        key = normalize_question(question)
        for stored_key, value in answers.items():
            if stored_key == key or (stored_key and stored_key in key):
                return QuestionDecision(
                    question=question,
                    category="test",
                    answer=value,
                    matched_key=stored_key,
                    rationale="test chooser",
                )
        return QuestionDecision(question=question)

    return choose


class _Task5BannerPage:
    """A minimal page that plays the Task 5 banner and the form-answer watcher."""

    def __init__(self, *, answer: str = "", done: bool = True, skip: bool = False) -> None:
        self.answer = answer
        self.done = done
        self.skip = skip
        self.shown = False
        self.hidden = False
        self.saved = False

    async def evaluate(self, js: str, *args):
        if "autojob-unknown" in js:
            if "getAttribute" in js:
                state = "skipped" if self.skip else "pending"
                return json.dumps({"present": True, "state": state})
            if "box.remove()" in js:
                self.hidden = True
                return True
            if "Saved" in js:
                self.saved = True
                return True
            self.shown = True
            return True
        if "__autojobFormAnswer" in js and "addEventListener" in js:
            return True
        if "__autojobFormAnswer" in js:
            return json.dumps({"value": self.answer, "done": self.done})
        return ""


class _DumpPage:
    """A page that returns markup for the unlabeled-question dump."""

    async def evaluate(self, js: str, *args):
        if "autojob-unknown" in js:
            if "getAttribute" in js:
                return json.dumps({"present": True, "state": "pending"})
            if "box.remove()" in js:
                return True
            return True
        if "__autojobFormAnswer" in js and "addEventListener" in js:
            return True
        if "__autojobFormAnswer" in js:
            return json.dumps({"value": "", "done": False})
        if "data-autojob-fill" in js:
            return json.dumps({"html": "<div role='radio'>Yes</div>"})
        return ""
