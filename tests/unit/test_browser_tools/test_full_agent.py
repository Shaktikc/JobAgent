"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

import pytest

from src.configuration import SessionSettings, Settings
from src.state import DEFAULT_LOGIN_URL
from src.tools import browser as browser_tools
from src.tools import linkedin_easy_apply_fill as fill_tools
from src.tools.linkedin import build_jobs_search_url
from src.tools.linkedin_best_matching_resume import selection as resume_selection
from src.tools.resume_descriptions import ResumeDescription, ResumeMatch

from .fakes import FakeElement, FakePage, FakeSession
from .helpers import (
    _filter_element,
    _job_card,
    _store_chooser,
    _text_field,
)

SEARCH_URL = build_jobs_search_url("software engineer")


async def test_run_full_agent_end_to_end_offline(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    resume_dir = tmp_path / "resumes"
    resume_dir.mkdir()
    (resume_dir / "ShaktiKC_Resume_python_Node_Senior.txt").write_text(
        "Senior Python engineer. Python, AWS, Docker, 8 years.", encoding="utf-8"
    )
    answers_file = tmp_path / "answers.json"
    answers_file.write_text('{"phone number": "+61 400 000 000"}', encoding="utf-8")

    page = FakePage(
        results_count=25,
        details_apply_labels={0: "Easy Apply to Backend Engineer at Acme"},
        form_enumerations=[
            {"open": True, "fields": [_text_field("f0", "phone", "Phone number", required=True)]}
        ],
        form_buttons_queue=[[{"marker": "b0", "text": "Submit application", "disabled": False}]],
        resume_options={
            "options": [
                {
                    "marker": "r0",
                    "label": "ShaktiKC_Resume_python_Node_Senior.txt",
                    "value": "",
                    "checked": False,
                }
            ],
            "fileInput": True,
        },
    )
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [_filter_element(page)],
        "li.jobs-search-results__list-item": [_job_card(page, 0, "Backend Engineer")],
    }
    page.fill_elements = {"f0": FakeElement("Phone number")}
    page.resume_elements = {"r0": FakeElement("ShaktiKC_Resume_python_Node_Senior.txt")}
    page.button_elements = {"b0": FakeElement("Submit application")}

    session = FakeSession(page)
    monkeypatch.setattr(browser_tools, "build_browser", lambda settings: session)
    # Task 4.1's LLM is a stand-in here (no network in unit tests): it chooses
    # stored answers exactly as the model is expected to.
    monkeypatch.setattr(
        fill_tools.form_walk,
        "build_fill_chooser",
        lambda settings, answers, context: _store_chooser(answers),
    )
    # Task 3.2's LLM is a stand-in here too (no network in unit tests): it describes
    # the pool and picks the only resume.
    async def fake_describe(path, settings, **kwargs):
        return ResumeDescription(summary="senior python engineer", skills=["python"])

    async def fake_pick(job_description, candidates, settings, **kwargs):
        return ResumeMatch(
            selected_path=candidates[0][0] if candidates else None,
            fit="strong",
            rationale="best fit",
        )

    monkeypatch.setattr(resume_selection, "describe_resume", fake_describe)
    monkeypatch.setattr(resume_selection, "pick_best_resume", fake_pick)

    settings = Settings(
        session=SessionSettings(
            headless=True,
            login_timeout_seconds=5,
            post_click_wait_seconds=0,
            ai_search_timeout_seconds=0,
            ask_human=False,
            # The form stops at the last step; keep the human-close wait short so
            # the offline run still closes the session and finishes.
            keep_open_timeout_seconds=0.05,
            keep_open_poll_seconds=0.01,
        ),
        data_dir=tmp_path,
        resumes_dir=resume_dir,
        answers_path=answers_file,
    )

    result = await browser_tools.run_full_agent(DEFAULT_LOGIN_URL, "software engineer", settings)

    assert result.task1.easy_apply_filter_selected is True
    assert result.task2.application_form_opened is True
    assert result.job_description.is_read is True
    assert result.task3.selected_path is not None
    assert result.task3.selected_path.endswith("ShaktiKC_Resume_python_Node_Senior.txt")
    assert result.task4.form_open is True
    assert result.task4.resume_selection == "listed"
    assert result.task4.filled_fields == 1
    assert result.task4.submitted is False
    assert page.button_elements["b0"].clicked is False
    assert session.killed is False
    assert session.stopped is True
    assert browser_tools._ACTIVE_RUNS == {}
