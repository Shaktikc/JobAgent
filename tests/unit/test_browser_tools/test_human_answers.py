"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

import pytest

from src.state import Task5Outcome
from src.tools import browser as browser_tools
from src.tools import linkedin_easy_apply_fill as fill_tools
from src.tools.linkedin import build_jobs_search_url

from .fakes import FakeElement, FakePage, FakeSession
from .helpers import (
    _human_asker,
    _radio_field,
    _settings,
    _store_chooser,
    _text_field,
)

SEARCH_URL = build_jobs_search_url("software engineer")


async def test_task5_asks_human_and_remembers_the_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """An unknown question is asked once, filled, stored, and reused from the store."""
    page = FakePage(
        form_enumerations=[
            {"open": True, "title": "Step 1",
             "fields": [_text_field("f0", "city", "City", required=True)]},
            {"open": True, "title": "Step 2",
             "fields": [_text_field("f1", "city", "City", required=True)]},
        ],
        form_buttons_queue=[
            [{"marker": "b0", "text": "Next", "disabled": False}],
            [{"marker": "b1", "text": "Submit application", "disabled": False}],
        ],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {"f0": FakeElement("City"), "f1": FakeElement("City")}
    page.button_elements = {"b0": FakeElement("Next"), "b1": FakeElement("Submit application")}
    calls: list[str] = []
    human = Task5Outcome()
    _human_asker(monkeypatch, "Sydney", calls)
    answers: dict[str, str] = {}
    settings = _settings(tmp_path, ask_human=True, post_click_wait_seconds=0)

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        None,
        answers,
        settings,
        lambda _m: None,
        human=human,
        chooser=_store_chooser(answers),
    )

    # Asked exactly once: step 2 reused the remembered answer with no prompt.
    assert calls == ["City *"]
    assert human.enabled is True
    assert human.asked == 1
    assert human.answered == 1
    assert human.answered_questions == ["City *"]

    assert page.fill_elements["f0"].filled == "Sydney"
    assert page.fill_elements["f1"].filled == "Sydney"
    assert outcome.known_fields == 2
    assert outcome.filled_fields == 2
    assert outcome.unknown_fields == []
    assert outcome.submitted is False
    # The first record came from the human, the repeat from the LLM (which now
    # finds the remembered answer in the store).
    assert [r.answered_by for r in outcome.fields if r.question == "City *"] == ["human", "llm"]

    # Persisted (normalized) and updated in memory for the rest of this run.
    assert browser_tools.load_answers(settings.answers_file)["city"] == "Sydney"
    assert answers["city"] == "Sydney"


async def test_task5_human_skip_leaves_the_question_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(
        form_enumerations=[
            {"open": True, "fields": [_text_field("f0", "city", "City", required=True)]}
        ],
        form_buttons_queue=[[{"marker": "b0", "text": "Submit application", "disabled": False}]],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {"f0": FakeElement("City")}
    page.button_elements = {"b0": FakeElement("Submit application")}
    calls: list[str] = []
    human = Task5Outcome()
    _human_asker(monkeypatch, None, calls)
    settings = _settings(tmp_path, ask_human=True, post_click_wait_seconds=0)

    outcome = await browser_tools._task4_on_page(
        page, FakeSession(page), None, {}, settings, lambda _m: None, human=human
    )

    assert calls == ["City *"]
    assert human.asked == 1
    assert human.skipped == 1
    assert outcome.unknown_fields == ["City *"]
    assert page.fill_elements["f0"].filled is None
    assert not settings.answers_file.exists()


async def test_task5_is_off_when_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    page = FakePage(
        form_enumerations=[
            {"open": True, "fields": [_text_field("f0", "city", "City", required=True)]}
        ],
        form_buttons_queue=[[{"marker": "b0", "text": "Submit application", "disabled": False}]],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {"f0": FakeElement("City")}
    page.button_elements = {"b0": FakeElement("Submit application")}
    called = False

    async def fake_ask(*args, **kwargs):
        nonlocal called
        called = True
        return "Sydney"

    monkeypatch.setattr(fill_tools.form_walk.core, "ask_human_for_answer", fake_ask)
    human = Task5Outcome()

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        None,
        {},
        _settings(tmp_path, post_click_wait_seconds=0),  # ask_human defaults off in tests
        lambda _m: None,
        human=human,
    )

    assert called is False
    assert human.enabled is False
    assert human.asked == 0
    assert outcome.unknown_fields == ["City *"]


async def test_task5_answers_a_required_radio_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    fields = [
        _radio_field("f0", "sponsor", "Do you require sponsorship?", "Yes", required=True),
        _radio_field("f1", "sponsor", "Do you require sponsorship?", "No", required=True),
    ]
    page = FakePage(
        form_enumerations=[{"open": True, "fields": fields}],
        form_buttons_queue=[[{"marker": "b0", "text": "Submit application", "disabled": False}]],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {"f0": FakeElement("Yes"), "f1": FakeElement("No")}
    page.button_elements = {"b0": FakeElement("Submit application")}
    calls: list[str] = []
    human = Task5Outcome()
    _human_asker(monkeypatch, "No", calls)
    settings = _settings(tmp_path, ask_human=True, post_click_wait_seconds=0)

    outcome = await browser_tools._task4_on_page(
        page, FakeSession(page), None, {}, settings, lambda _m: None, human=human
    )

    # The human's "No" matched only the "No" option.
    assert calls == ["Do you require sponsorship? *"]
    assert page.fill_elements["f0"].clicked is False
    assert page.fill_elements["f1"].clicked is True
    assert outcome.known_fields == 1
    assert outcome.filled_fields == 1
    assert browser_tools.load_answers(settings.answers_file)["do you require sponsorship"] == "No"


async def test_task5_skips_prefilled_controls(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A pre-filled select (e.g. the profile email) is left alone and not asked about."""
    fields = [
        {
            "marker": "f0",
            "kind": "select",
            "type": "select",
            "name": "email",
            "question": "Email address *",
            "option": "",
            "required": True,
            "checked": False,
            "value": "me@example.com",
            "options": [{"value": "me@example.com", "text": "me@example.com"}],
        },
        _text_field("f1", "phone", "Mobile phone number", required=True),
    ]
    page = FakePage(
        form_enumerations=[{"open": True, "title": "Contact info", "fields": fields}],
        form_buttons_queue=[[{"marker": "b0", "text": "Submit application", "disabled": False}]],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {
        "f0": FakeElement("Email address"),
        "f1": FakeElement("Mobile phone number"),
    }
    page.button_elements = {"b0": FakeElement("Submit application")}
    calls: list[str] = []
    human = Task5Outcome()
    _human_asker(monkeypatch, "+61 400 000 000", calls)
    settings = _settings(tmp_path, ask_human=True, post_click_wait_seconds=0)

    outcome = await browser_tools._task4_on_page(
        page, FakeSession(page), None, {}, settings, lambda _m: None, human=human
    )

    # Only the genuinely-empty required field was asked; the email select was not.
    assert calls == ["Mobile phone number *"]
    assert page.fill_elements["f0"].selected_option is None
    assert page.fill_elements["f1"].filled == "+61 400 000 000"
    assert outcome.unknown_fields == []
    assert [r.answered_by for r in outcome.fields if r.question == "Email address *"] == ["form"]
    stored = browser_tools.load_answers(settings.answers_file)
    assert stored.get("mobile phone number") == "+61 400 000 000"
    assert "email address" not in stored


async def test_task5_select_answer_matches_option_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A human may type a select's visible label; it must map to the option value."""
    fields = [
        {
            "marker": "f0",
            "kind": "select",
            "type": "select",
            "name": "contact_method",
            "question": "Preferred contact method *",
            "option": "",
            "required": True,
            "checked": False,
            "value": "",
            "options": [
                {"value": "em", "text": "Email"},
                {"value": "ph", "text": "Phone"},
            ],
        }
    ]
    page = FakePage(
        form_enumerations=[{"open": True, "fields": fields}],
        form_buttons_queue=[[{"marker": "b0", "text": "Submit application", "disabled": False}]],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {"f0": FakeElement("Preferred contact method")}
    page.button_elements = {"b0": FakeElement("Submit application")}
    calls: list[str] = []
    human = Task5Outcome()
    _human_asker(monkeypatch, "Phone", calls)
    settings = _settings(tmp_path, ask_human=True, post_click_wait_seconds=0)

    outcome = await browser_tools._task4_on_page(
        page, FakeSession(page), None, {}, settings, lambda _m: None, human=human
    )

    assert calls == ["Preferred contact method *"]
    # The visible label "Phone" was mapped to the option value "ph".
    assert page.fill_elements["f0"].selected_option == "ph"
    assert outcome.filled_fields == 1
    assert browser_tools.load_answers(settings.answers_file)["preferred contact method"] == "Phone"
