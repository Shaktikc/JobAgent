"""Automatic submission must guard the click and observe fresh confirmation."""

from types import SimpleNamespace

import pytest

from src.configuration import SessionSettings, Settings
from src.state import FormField, Task4Outcome
from src.state.validation import ValidationIssue
from src.tools import linkedin_auto_submit as submit


def complete_form():
    return Task4Outcome(form_open=True, reached_terminal_step=True, resume_attached=True)


def test_site_boundary_and_required_groups():
    assert submit._is_linkedin_jobs_url("https://www.linkedin.com/jobs/view/123/")
    for url in ["https://linkedin.com.evil/jobs/", "http://linkedin.com/jobs/",
                "https://example.com/jobs/", "https://linkedin.com/feed/"]:
        assert not submit._is_linkedin_jobs_url(url)
    assert submit._unanswered_required([{"required": True, "value": ""}])
    assert not submit._unanswered_required([
        {"kind": "radio", "name": "yesno", "required": True, "checked": False},
        {"kind": "radio", "name": "yesno", "required": True, "checked": True},
    ])
    assert not submit._unanswered_required([
        {"kind": "checkbox", "name": "a", "question": "Skills *", "required": True,
         "checked": True},
        {"kind": "checkbox", "name": "b", "question": "Skills *", "required": True,
         "checked": False},
    ])


@pytest.mark.asyncio
async def test_incomplete_form_never_reaches_the_browser():
    result = await submit._submit_on_page(None, Task4Outcome(), Settings(), print)
    assert result.status == "blocked"
    outcome = complete_form()
    outcome.fields = [FormField(question="Required *", required=True)]
    result = await submit._submit_on_page(None, outcome, Settings(), print)
    assert result.status == "blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize("result", ["immediate", "missing", "read_error", "click_error"])
async def test_click_once_and_confirm_before_counting(monkeypatch, result):
    outcome = complete_form()
    clicks = []
    initial = dict(form_open=True, confirmation="", card_applied=False, status_submitted=False)
    async def click():
        clicks.append(1)
        if result == "click_error":
            raise RuntimeError("CDP disconnected after dispatch")
    async def prepare(*_):
        return SimpleNamespace(click=click), initial, ""
    async def read(*_):
        if result == "read_error":
            raise RuntimeError("lost connection")
        return {**initial, "form_open": False,
                "confirmation": "Application submitted" if result == "immediate" else ""}
    async def dismiss(*_):
        pass
    monkeypatch.setattr(submit, "_prepare_submit", prepare)
    monkeypatch.setattr(submit, "_read_state", read)
    monkeypatch.setattr(submit, "_dismiss_confirmation", dismiss)
    settings = Settings(session=SessionSettings(
        auto_submit_timeout_seconds=0.01, keep_open_poll_seconds=0.01,
    ))
    observed = await submit._submit_on_page(None, outcome, settings, lambda _: None)
    assert clicks == [1]
    assert outcome.submission_attempted
    assert outcome.submitted == (result == "immediate")
    assert observed.status == ("submitted" if result == "immediate" else "unconfirmed")


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", [
    "ready", "no_form", "unknown", "validation", "ambiguous", "disabled", "next",
    "native_invalid", "not_ready", "already_attempted", "skipped",
])
async def test_current_form_is_checked_before_submission(monkeypatch, scenario):
    outcome = complete_form()
    outcome.submission_attempted = scenario == "already_attempted"
    if scenario == "skipped":
        outcome.validation.issues = [ValidationIssue(message="Invalid input")]
        outcome.validation.logged = outcome.validation.modal_closed = True
    async def form(_):
        fields = [{"required": True, "value": ""}] if scenario == "unknown" else []
        return scenario != "no_form", "Review", fields, "step"
    async def rejections(*_):
        return [{}] if scenario == "validation" else []
    async def buttons(_):
        control = {"text": "Submit application", "marker": "submit",
                   "disabled": scenario == "disabled"}
        if scenario == "ambiguous":
            return [control, control]
        if scenario == "next":
            return [control, {"text": "Next", "marker": "next"}]
        return [control]
    async def evaluate(_):
        import json
        return json.dumps({"ready": scenario != "not_ready",
                           "invalid": scenario == "native_invalid"})
    async def element(*_):
        return SimpleNamespace(evaluate=evaluate)
    async def read(*_):
        return {"confirmation": ""}
    monkeypatch.setattr(submit, "read_form", form)
    monkeypatch.setattr(submit, "read_rejections", rejections)
    monkeypatch.setattr(submit, "read_form_buttons", buttons)
    monkeypatch.setattr(submit, "_marker_element", element)
    monkeypatch.setattr(submit, "_read_state", read)
    element, initial, reason = await submit._prepare_submit(None, outcome, "Job", "Company")
    assert bool(element) == (scenario == "ready")
    assert bool(reason) == (scenario != "ready")
