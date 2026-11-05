"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

import pytest

from src.tools import browser as browser_tools
from src.tools import linkedin_easy_apply_fill as fill_tools
from src.tools.linkedin import build_jobs_search_url

from .fakes import FakeElement, FakePage, FakeSession
from .helpers import (
    _contact_step_fields,
    _settings,
    _store_chooser,
    _text_field,
)

SEARCH_URL = build_jobs_search_url("software engineer")


async def test_enumerate_form_fields() -> None:
    page = FakePage(
        form_enumerations=[
            {"open": True, "fields": [{"marker": "f0", "kind": "input", "question": "Name"}]}
        ]
    )
    opened, fields = await browser_tools.enumerate_form_fields(page)

    assert opened is True
    assert fields[0]["marker"] == "f0"


async def test_enumerate_form_fields_reports_closed_form() -> None:
    opened, fields = await browser_tools.enumerate_form_fields(FakePage())
    assert opened is False
    assert fields == []


async def test_task4_fills_form_and_selects_listed_resume(tmp_path) -> None:
    fields = [
        _text_field("f0", "phone", "Phone number", required=True),
        _text_field("f1", "city", "City", required=True),
        {
            "marker": "f2",
            "kind": "radio",
            "type": "radio",
            "name": "work_auth",
            "question": "Are you authorised to work in Australia? *",
            "option": "Yes",
            "required": True,
            "checked": False,
            "value": "",
            "options": [],
        },
        {
            "marker": "f3",
            "kind": "radio",
            "type": "radio",
            "name": "work_auth",
            "question": "Are you authorised to work in Australia? *",
            "option": "No",
            "required": True,
            "checked": False,
            "value": "",
            "options": [],
        },
        {
            "marker": "f4",
            "kind": "select",
            "type": "select",
            "name": "experience",
            "question": "Years of experience *",
            "option": "",
            "required": True,
            "checked": False,
            "value": "",
            "options": [{"value": "5", "text": "5"}],
        },
    ]
    page = FakePage(
        form_enumerations=[{"open": True, "fields": fields}],
        form_buttons_queue=[[{"marker": "b0", "text": "Submit application", "disabled": False}]],
        resume_options={
            "options": [
                {
                    "marker": "r0",
                    "label": "ShaktiKC_Resume_python_Node_Senior.pdf",
                    "value": "",
                    "checked": False,
                }
            ],
            "fileInput": True,
        },
    )
    page.fill_elements = {
        "f0": FakeElement("Phone number"),
        "f1": FakeElement("City"),
        "f2": FakeElement("Yes"),
        "f3": FakeElement("No"),
        "f4": FakeElement("Years of experience"),
    }
    page.resume_elements = {"r0": FakeElement("ShaktiKC_Resume_python_Node_Senior.pdf")}
    page.button_elements = {"b0": FakeElement("Submit application")}
    answers = {
        "phone number": "+61 400 000 000",
        "are you authorised to work in australia": "Yes",
        "years of experience": "5",
    }

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        "resumes/ShaktiKC_Resume_python_Node_Senior.pdf",
        answers,
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
        chooser=_store_chooser(answers),
    )

    assert outcome.form_open is True
    assert outcome.fields_enumerated == 5
    assert outcome.known_fields == 3
    assert outcome.filled_fields == 3
    assert outcome.unknown_fields == ["City *"]
    assert page.fill_elements["f0"].filled == "+61 400 000 000"
    assert page.fill_elements["f2"].clicked is True
    assert page.fill_elements["f3"].clicked is False
    assert page.fill_elements["f4"].selected_option == "5"
    assert outcome.resume_attached is True
    assert outcome.resume_selection == "listed"
    assert page.resume_elements["r0"].clicked is True
    # Each LLM (Task 4.1) decision records the classification, chosen key, and why.
    llm_fields = [f for f in outcome.fields if f.answered_by == "llm"]
    assert llm_fields
    assert all(
        f.question_type == "test" and f.matched_key and f.rationale == "test chooser"
        for f in llm_fields
    )
    # The one available button is Submit; it must never be clicked.
    assert outcome.submitted is False
    assert outcome.steps_advanced == 0
    # Only Submit remains, so this is the terminal step: the browser is left open
    # for the human (see cleanup).
    assert outcome.reached_terminal_step is False
    assert "City" in outcome.notes  # A required unknown cannot be reported ready for Submit.
    assert page.button_elements["b0"].clicked is False


async def test_task4_uploads_resume_when_not_listed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(
        form_enumerations=[{"open": True, "fields": [_text_field("f0", "phone", "Phone number")]}],
        form_buttons_queue=[[]],
        resume_options={
            "options": [
                {"marker": "r0", "label": "Some_Other_Resume.pdf", "value": "", "checked": False}
            ],
            "fileInput": True,
        },
    )
    page.fill_elements = {"f0": FakeElement("Phone number")}
    page.file_element = FakeElement("file")

    uploaded: dict = {}

    async def fake_upload(session, page, selector: str, path: str) -> None:
        uploaded["selector"] = selector
        uploaded["path"] = path

    monkeypatch.setattr(fill_tools.resume_attachment, "upload_file_via_cdp", fake_upload)

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        "resumes/ShaktiKC_Resume_python_Node_Senior.pdf",
        {},
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
    )

    assert outcome.upload_attempted is True
    assert outcome.resume_attached is True
    assert outcome.resume_selection == "uploaded"
    assert uploaded["path"].endswith("ShaktiKC_Resume_python_Node_Senior.pdf")
    assert uploaded["selector"] == '[data-autojob-file="1"]'


async def test_task4_advances_steps_but_never_submits(tmp_path) -> None:
    page = FakePage(
        form_enumerations=[
            {"open": True, "fields": [_text_field("f0", "phone", "Phone number", required=True)]},
            {"open": True, "fields": [_text_field("f1", "city", "City", required=True)]},
        ],
        form_buttons_queue=[
            [{"marker": "b0", "text": "Next", "disabled": False}],
            [{"marker": "b1", "text": "Submit application", "disabled": False}],
        ],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {"f0": FakeElement("Phone number"), "f1": FakeElement("City")}
    page.button_elements = {
        "b0": FakeElement("Next"),
        "b1": FakeElement("Submit application"),
    }

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        "resumes/ShaktiKC_Resume_python_Node_Senior.pdf",
        {"phone number": "+61", "city": "Sydney"},
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
        chooser=_store_chooser({"phone number": "+61", "city": "Sydney"}),
    )

    assert outcome.steps_advanced == 1
    assert page.button_elements["b0"].clicked is True
    assert page.button_elements["b1"].clicked is False
    assert outcome.submitted is False
    assert outcome.known_fields == 2
    assert outcome.filled_fields == 2
    assert outcome.resume_attached is False
    assert "no resume control" in outcome.notes


async def test_task4_follows_dynamic_form_and_selects_resume_from_select(tmp_path) -> None:
    """The resume may be on any step and rendered as a <select>, not a radio."""
    page = FakePage(
        form_enumerations=[
            {"open": True, "title": "Contact info", "fields": _contact_step_fields()},
            {"open": True, "title": "Resume", "fields": []},
        ],
        form_buttons_queue=[
            [{"marker": "b0", "text": "Next", "disabled": False}],
            [{"marker": "b1", "text": "Submit application", "disabled": False}],
        ],
        resume_options=[
            {"options": [], "fileInput": False, "select": None, "uploadButton": None},
            {
                "options": [],
                "fileInput": False,
                "uploadButton": None,
                "select": {
                    "marker": "s0",
                    "label": "Select a resume",
                    "options": [
                        {"value": "other", "text": "Other_Resume.pdf"},
                        {"value": "chosen", "text": "ShaktiKC_Resume_python_Node_Senior.pdf"},
                    ],
                },
            },
        ],
    )
    page.fill_elements = {
        "f0": FakeElement("Email address"),
        "f1": FakeElement("Phone country code"),
        "f2": FakeElement("Mobile phone number"),
    }
    page.select_elements = {"s0": FakeElement("Select a resume")}
    page.button_elements = {"b0": FakeElement("Next"), "b1": FakeElement("Submit application")}

    answers = {
        "email address": "me@example.com",
        "phone country code": "Australia (+61)",
        "mobile phone number": "400000000",
    }
    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        "resumes/ShaktiKC_Resume_python_Node_Senior.pdf",
        answers,
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
        chooser=_store_chooser(answers),
    )

    assert outcome.form_open is True
    assert outcome.steps_advanced == 1
    assert outcome.resume_attached is True
    assert outcome.resume_selection == "listed"
    assert outcome.resume_listed_name == "ShaktiKC_Resume_python_Node_Senior.pdf"
    assert page.select_elements["s0"].selected_option == "chosen"
    assert outcome.submitted is False


async def test_task4_clicks_upload_button_to_reveal_file_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """When no resume control is visible, an Upload button may reveal the input."""
    page = FakePage(
        form_enumerations=[{"open": True, "title": "Resume", "fields": []}],
        form_buttons_queue=[[{"marker": "b0", "text": "Submit application", "disabled": False}]],
        resume_options=[
            {
                "options": [],
                "fileInput": False,
                "select": None,
                "uploadButton": {"marker": "u0", "label": "Upload resume"},
            },
            {"options": [], "fileInput": True, "select": None, "uploadButton": None},
        ],
    )
    page.upload_elements = {
        "u0": FakeElement(
            "Upload resume",
            on_click=lambda: setattr(page, "file_element", FakeElement("file")),
        )
    }

    uploaded: dict = {}

    async def fake_upload(session, page, selector: str, path: str) -> None:
        uploaded["selector"] = selector
        uploaded["path"] = path

    monkeypatch.setattr(fill_tools.resume_attachment, "upload_file_via_cdp", fake_upload)

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        "resumes/ShaktiKC_Resume_python_Node_Senior.pdf",
        {},
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
    )

    assert page.upload_elements["u0"].clicked is True
    assert outcome.resume_attached is True
    assert outcome.resume_selection == "uploaded"
    assert uploaded["path"].endswith("ShaktiKC_Resume_python_Node_Senior.pdf")
