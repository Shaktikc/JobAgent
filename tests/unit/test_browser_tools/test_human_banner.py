"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

import pytest

from src.state import Task5Outcome
from src.tools import browser as browser_tools
from src.tools import linkedin_ask_human as ask_human_tools
from src.tools.linkedin import build_jobs_search_url

from .fakes import FakeElement, FakePage, FakeSession
from .helpers import (
    _DumpPage,
    _human_asker,
    _radio_field,
    _settings,
    _Task5BannerPage,
    _text_field,
)

SEARCH_URL = build_jobs_search_url("software engineer")


async def test_task5_reads_the_answer_typed_into_the_form(tmp_path) -> None:
    """The banner has no input: the answer is read from the form field the human edits."""
    page = _Task5BannerPage(answer="Sydney", done=True)
    notes: list[str] = []
    human = Task5Outcome()
    settings = _settings(tmp_path, ask_human=True, ask_poll_seconds=0.01)

    answer = await browser_tools.ask_human_for_answer(
        page, "City", "text", "", settings, notes.append, human
    )

    assert answer == "Sydney"
    assert page.shown is True
    assert page.hidden is True
    assert page.saved is True  # the banner confirmed the answer was stored
    assert human.asked == 1
    assert human.answered == 1
    assert human.answered_questions == ["City"]
    assert any("City" in note for note in notes)


async def test_task5_empty_form_edit_keeps_waiting(tmp_path) -> None:
    """An empty edit never counts as an answer; the wait times out instead."""
    page = _Task5BannerPage(answer="", done=True)
    human = Task5Outcome()
    settings = _settings(
        tmp_path, ask_human=True, ask_timeout_seconds=0.05, ask_poll_seconds=0.01
    )

    answer = await browser_tools.ask_human_for_answer(
        page, "City", "text", "", settings, lambda _m: None, human
    )

    assert answer is None
    assert human.answered == 0
    assert human.timed_out == 1


async def test_task5_never_stores_an_unfinished_answer(tmp_path) -> None:
    """Recovery must not save or use a partial answer when the wait times out."""
    page = _Task5BannerPage(answer="Sydney", done=False)
    human = Task5Outcome()
    settings = _settings(
        tmp_path, ask_human=True, ask_timeout_seconds=0.05, ask_poll_seconds=0.01
    )

    answer = await browser_tools.ask_human_for_answer(
        page, "City", "text", "", settings, lambda _m: None, human
    )

    assert answer is None
    assert human.answered == 0
    assert human.timed_out == 1
    assert browser_tools.load_answers(settings.answers_file) == {}
    assert not page.saved


async def test_task5_asks_questions_in_form_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A choice is asked at its place in the form, not before every text box."""
    fields = [
        _text_field("f0", "years", "Years of experience", required=True),
        _radio_field("f1", "rights", "Working rights?", "Yes", required=True),
        _radio_field("f2", "rights", "Working rights?", "No", required=True),
        _text_field("f3", "notice", "Notice period", required=True),
    ]
    page = FakePage(
        form_enumerations=[{"open": True, "fields": fields}],
        form_buttons_queue=[
            [{"marker": "b0", "text": "Submit application", "disabled": False}]
        ],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {m: FakeElement(m) for m in ("f0", "f1", "f2", "f3")}
    page.button_elements = {"b0": FakeElement("Submit application")}
    calls: list[str] = []
    _human_asker(monkeypatch, "X", calls)
    settings = _settings(tmp_path, ask_human=True, post_click_wait_seconds=0)

    await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        None,
        {},
        settings,
        lambda _m: None,
        human=Task5Outcome(),
    )

    # Questions are asked in the order they appear on the form.
    assert calls == ["Years of experience *", "Working rights? *", "Notice period *"]


def test_task5_flags_a_raw_form_id_as_unlabeled() -> None:
    assert ask_human_tools._looks_unlabeled("radio-group-_r_1t_") is True
    assert ask_human_tools._looks_unlabeled("") is True
    assert ask_human_tools._looks_unlabeled("Are you comfortable working onsite?") is False


async def test_task5_dumps_the_markup_for_an_unlabeled_question(tmp_path) -> None:
    page = _DumpPage()
    settings = _settings(
        tmp_path, ask_human=True, ask_timeout_seconds=0.05, ask_poll_seconds=0.01
    )

    answer = await browser_tools.ask_human_for_answer(
        page,
        "radio-group-_r_1t_",
        "radio",
        "",
        settings,
        lambda _m: None,
        Task5Outcome(),
        markers=["f0"],
    )

    assert answer is None
    dumps = list(settings.debug_dir.glob("task5_context_*.html"))
    assert len(dumps) == 1
    assert dumps[0].read_text(encoding="utf-8") == "<div role='radio'>Yes</div>"


async def test_task5_skip_still_leaves_the_question_unknown(tmp_path) -> None:
    """The banner keeps a Skip button; skipping returns no answer."""
    page = _Task5BannerPage(skip=True)
    human = Task5Outcome()
    settings = _settings(tmp_path, ask_human=True, ask_poll_seconds=0.01)

    answer = await browser_tools.ask_human_for_answer(
        page, "City", "text", "", settings, lambda _m: None, human
    )

    assert answer is None
    assert human.skipped == 1
    assert human.answered == 0
