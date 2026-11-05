"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

from src.tools import browser as browser_tools
from src.tools import linkedin_easy_apply_fill as fill_tools
from src.tools.linkedin import build_jobs_search_url

from .fakes import FakeElement, FakePage, FakeSession
from .helpers import (
    _contact_step_fields,
    _settings,
)

SEARCH_URL = build_jobs_search_url("software engineer")


async def test_task4_stops_when_dynamic_form_does_not_advance(tmp_path) -> None:
    """A required unknown field blocks Next; stop instead of re-clicking forever."""
    fields = _contact_step_fields()
    page = FakePage(
        form_enumerations=[
            {"open": True, "title": "Contact info", "fields": fields},
            {"open": True, "title": "Contact info", "fields": fields},
            {"open": True, "title": "Contact info", "fields": fields},
        ],
        form_buttons_queue=[
            [{"marker": "b0", "text": "Next", "disabled": False}] for _ in range(3)
        ],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {
        "f0": FakeElement("Email address"),
        "f1": FakeElement("Phone country code"),
        "f2": FakeElement("Mobile phone number"),
    }
    page.button_elements = {"b0": FakeElement("Next")}

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        None,
        {},
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
    )

    # A step that did not actually advance must not be counted as advanced.
    assert outcome.steps_advanced == 0
    assert "did not advance" in outcome.notes
    # The note names the required answers that blocked Next, for a clear stop.
    assert "Email address" in outcome.notes
    assert "Mobile phone number" in outcome.notes
    # Required-answer preflight now stops before clicking an unresolved step.
    assert page.button_elements["b0"].clicked is False


async def test_task4_stops_clearly_when_next_is_disabled(tmp_path) -> None:
    """A disabled Next (required answer unknown) stops with a clear, named note."""
    fields = _contact_step_fields()  # all required, none answered
    page = FakePage(
        form_enumerations=[{"open": True, "title": "Contact info", "fields": fields}],
        form_buttons_queue=[[{"marker": "b0", "text": "Next", "disabled": True}]],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {
        "f0": FakeElement("Email address"),
        "f1": FakeElement("Phone country code"),
        "f2": FakeElement("Mobile phone number"),
    }
    page.button_elements = {"b0": FakeElement("Next")}

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        None,
        {},
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
    )

    assert outcome.steps_advanced == 0
    assert outcome.submitted is False
    assert page.button_elements["b0"].clicked is False
    assert "disabled" in outcome.notes
    assert "Email address" in outcome.notes
    assert "stopping before Submit" in outcome.notes


async def test_task4_reports_missing_form(tmp_path) -> None:
    page = FakePage(form_open_default=False)

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        "resumes/a.pdf",
        {},
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
    )

    assert outcome.form_open is False
    assert "form was not found" in outcome.notes


def test_task4_form_queries_ignore_hidden_dialogs() -> None:
    """All Task 4 queries pick the visible Easy Apply modal, not merely the first match.

    A real jobs page can carry an unrelated hidden ``.artdeco-modal`` (e.g.
    "Save this job") earlier in the DOM. A bare ``document.querySelector`` would
    pick it, enumerate zero fields, and fill nothing, so every Task 4 query must
    resolve the modal through the shared visibility-aware helper.
    """
    queries = {
        "enumerate": fill_tools._ENUMERATE_FORM_QUERY,
        "resume": fill_tools._RESUME_OPTIONS_QUERY,
        "buttons": fill_tools._FORM_BUTTONS_QUERY,
    }
    for name, query in queries.items():
        assert "findApplyRoot" in query, f"{name} query lost the form finder"
        assert "getClientRects" in query, f"{name} query no longer checks visibility"
        assert "const modal = document.querySelector(" not in query, name


def test_task2_apply_modal_query_uses_shared_form_finder() -> None:
    """Task 2 must detect both the classic modal and the inline semantic form."""
    query = browser_tools._APPLY_MODAL_QUERY
    assert "findApplyRoot" in query
    assert "getClientRects" in query
