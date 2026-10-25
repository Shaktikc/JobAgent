"""Unit tests for Task 8's submit-detection and next-job helpers (no browser)."""

from __future__ import annotations

import json
import re

from src.configuration import SessionSettings, Settings
from src.state import JobDescription, Task2Outcome
from src.tools import browser as browser_tools
from src.tools import linkedin_apply_loop as loop
from src.tools.linkedin_apply_loop import (
    await_human_submit,
    looks_like_submission,
    open_next_job,
    read_submission_state,
    submission_detected,
)


def _settings(**session) -> Settings:
    session.setdefault("post_click_wait_seconds", 0)
    return Settings(session=SessionSettings(**session))


class _FakeElement:
    def __init__(self) -> None:
        self.clicked = False

    async def click(self) -> None:
        self.clicked = True


class _FakeSession:
    def __init__(self, page) -> None:
        self.page = page
        self.killed = False
        self.stopped = False
        self.is_cdp_connected = True

    async def kill(self) -> None:
        self.killed = True

    async def stop(self) -> None:
        # Releasing the session must never close the browser.
        self.stopped = True


class _FakeSubmitPage:
    """Answers Task 8's submission probe with canned payload(s)."""

    def __init__(self, payload: dict | list[dict]) -> None:
        self.payloads = list(payload) if isinstance(payload, list) else [payload]
        self.done_elements: dict[str, _FakeElement] = {}

    async def evaluate(self, js: str, *args):
        if "data-autojob-done" in js:
            payload = self.payloads.pop(0) if len(self.payloads) > 1 else self.payloads[0]
            return json.dumps(payload)
        return ""

    async def get_elements_by_css_selector(self, selector: str) -> list:
        match = re.fullmatch(r'\[data-autojob-done="([^"]+)"\]', selector)
        if match:
            element = self.done_elements.get(match.group(1))
            return [element] if element is not None else []
        return []


def _register(run_id: str, page, *, connected: bool = True) -> _FakeSession:
    session = _FakeSession(page)
    session.is_cdp_connected = connected
    browser_tools._ACTIVE_RUNS[run_id] = browser_tools._Run(session=session, page=page)
    return session


# --- pure detection -------------------------------------------------------


def test_looks_like_submission_matches_confirmation_phrases() -> None:
    assert looks_like_submission("Your application was sent to Acme")
    assert looks_like_submission("Application sent")
    assert looks_like_submission("  application submitted  ")
    assert looks_like_submission("You've applied to Backend Engineer")


def test_looks_like_submission_ignores_other_text() -> None:
    assert not looks_like_submission("")
    assert not looks_like_submission("Easy Apply to Backend Engineer")
    assert not looks_like_submission("Applied")
    assert not looks_like_submission("Backend Engineer Acme Applied 5 months ago")


def test_submission_detected_prefers_the_confirmation() -> None:
    assert submission_detected(confirmation="Application sent", form_open=False, card_applied=False)
    # A confirmation still counts while the form is technically open.
    assert submission_detected(confirmation="Application sent", form_open=True, card_applied=False)


def test_submission_detected_falls_back_to_the_applied_card() -> None:
    # Form closed and the job's card now reads Applied -> submitted.
    assert submission_detected(confirmation="", form_open=False, card_applied=True)
    # Form closed but the card is not Applied -> a dismissed modal, not a submit.
    assert not submission_detected(confirmation="", form_open=False, card_applied=False)
    # Card Applied but the form still open -> not a submission yet.
    assert not submission_detected(confirmation="", form_open=True, card_applied=True)
    # A card that already read Applied before the wait is stale, not a submit.
    assert not submission_detected(
        confirmation="", form_open=False, card_applied=True, card_was_applied=True
    )


# --- read_submission_state -------------------------------------------------


async def test_read_submission_state_reads_the_probe() -> None:
    page = _FakeSubmitPage(
        {
            "form_open": False,
            "confirmation": "Application sent",
            "card_applied": True,
            "done_marker": "d0",
        }
    )
    state = await read_submission_state(page, title="Backend Engineer")
    assert state == {
        "form_open": False,
        "confirmation": "Application sent",
        "card_applied": True,
        "done_marker": "d0",
    }


# --- await_human_submit ----------------------------------------------------


async def test_await_human_submit_detects_a_submission_and_dismisses() -> None:
    page = _FakeSubmitPage(
        [
            {"form_open": True, "confirmation": "", "card_applied": False},
            {
                "form_open": False,
                "confirmation": "Application sent",
                "card_applied": False,
                "done_marker": "d0",
            },
        ]
    )
    done = _FakeElement()
    page.done_elements["d0"] = done
    _register("run-submit", page)

    try:
        result = await await_human_submit("run-submit", _settings(), title="Backend Engineer")
    finally:
        browser_tools._ACTIVE_RUNS.pop("run-submit", None)

    assert result == "submitted"
    assert done.clicked is True


async def test_await_human_submit_ignores_a_card_already_applied_before_the_wait() -> None:
    # A stale "Applied" card plus a dismissed form must NOT advance the loop:
    # nothing was submitted for this job during the wait.
    page = _FakeSubmitPage(
        [
            {"form_open": False, "confirmation": "", "card_applied": True},
            {"form_open": False, "confirmation": "", "card_applied": True},
        ]
    )
    _register("run-stale-applied", page)

    try:
        result = await await_human_submit(
            "run-stale-applied",
            _settings(keep_open_timeout_seconds=0.05, keep_open_poll_seconds=0.01),
        )
    finally:
        browser_tools._ACTIVE_RUNS.pop("run-stale-applied", None)

    assert result == "timeout"


async def test_await_human_submit_ignores_a_stale_confirmation_from_the_previous_job() -> None:
    # The previous job's "Application sent" dialog stayed on the results page.
    # It must not make this job look submitted (which opened the next job by itself).
    page = _FakeSubmitPage(
        [
            {"form_open": False, "confirmation": "Application sent", "card_applied": False},
            {"form_open": True, "confirmation": "Application sent", "card_applied": False},
            {"form_open": True, "confirmation": "Application sent", "card_applied": False},
        ]
    )
    _register("run-stale-confirmation", page)

    try:
        result = await await_human_submit(
            "run-stale-confirmation",
            _settings(keep_open_timeout_seconds=0.05, keep_open_poll_seconds=0.01),
        )
    finally:
        browser_tools._ACTIVE_RUNS.pop("run-stale-confirmation", None)

    assert result == "timeout"


async def test_await_human_submit_detects_a_card_flipping_to_applied() -> None:
    # The fallback still works when the card flips during the wait (the human
    # submitted and dismissed the confirmation before the next poll).
    page = _FakeSubmitPage(
        [
            {"form_open": True, "confirmation": "", "card_applied": False},
            {"form_open": False, "confirmation": "", "card_applied": True},
        ]
    )
    _register("run-flip", page)

    try:
        result = await await_human_submit(
            "run-flip",
            _settings(keep_open_timeout_seconds=0.2, keep_open_poll_seconds=0.01),
        )
    finally:
        browser_tools._ACTIVE_RUNS.pop("run-flip", None)

    assert result == "submitted"


async def test_await_human_submit_reports_a_closed_browser() -> None:
    page = _FakeSubmitPage({"form_open": False, "confirmation": ""})
    session = _register("run-closed", page, connected=False)

    try:
        result = await await_human_submit("run-closed", _settings())
    finally:
        browser_tools._ACTIVE_RUNS.pop("run-closed", None)

    assert result == "closed"
    # The window is already gone; the run is just forgotten.
    assert session.killed is False
    assert browser_tools.get_run("run-closed") is None


async def test_await_human_submit_times_out_and_leaves_open() -> None:
    page = _FakeSubmitPage({"form_open": True, "confirmation": "", "card_applied": False})
    session = _register("run-timeout", page)

    try:
        result = await await_human_submit(
            "run-timeout",
            _settings(keep_open_timeout_seconds=0.05, keep_open_poll_seconds=0.01),
        )
    finally:
        browser_tools._ACTIVE_RUNS.pop("run-timeout", None)

    assert result == "timeout"
    # The browser is left open, never killed.
    assert session.killed is False
    assert session.stopped is True


async def test_await_human_submit_returns_closed_without_a_run() -> None:
    assert await await_human_submit("missing", _settings()) == "closed"


# --- open_next_job ---------------------------------------------------------


async def test_open_next_job_opens_and_reads_the_description(monkeypatch) -> None:
    import src.tools.linkedin_best_matching_resume as resume_tools

    page = object()
    _register("run-next", page)
    captured: dict = {}

    async def fake_task2(p, settings, notify, skip_keys=None, capture=None):
        captured["skip_keys"] = skip_keys
        return Task2Outcome(
            jobs_seen=5,
            job_index=1,
            job_title="Data Engineer",
            easy_apply_clicked=True,
            application_form_opened=True,
        )

    async def fake_read(p):
        return JobDescription(title="Data Engineer", company="Acme")

    monkeypatch.setattr(loop, "_task2_on_page", fake_task2)
    monkeypatch.setattr(resume_tools, "read_job_description", fake_read)

    try:
        result = await open_next_job("run-next", _settings(), skip_title="Backend Engineer")
    finally:
        browser_tools._ACTIVE_RUNS.pop("run-next", None)

    assert result.opened is True
    assert result.description.company == "Acme"
    # The just-submitted job is excluded even before its card flips to Applied.
    assert captured["skip_keys"] == {"backend engineer"}


async def test_open_next_job_reports_when_every_job_is_applied(monkeypatch) -> None:
    page = object()
    _register("run-none", page)

    async def fake_task2(p, settings, notify, skip_keys=None, capture=None):
        return Task2Outcome(
            jobs_seen=3,
            applied_jobs_skipped=3,
            notes="no unapplied job found on this page; every job card is already Applied",
        )

    monkeypatch.setattr(loop, "_task2_on_page", fake_task2)

    try:
        result = await open_next_job("run-none", _settings())
    finally:
        browser_tools._ACTIVE_RUNS.pop("run-none", None)

    assert result.opened is False
    assert result.reason == "every job on every results page is already Applied"


async def test_open_next_job_reports_a_closed_session() -> None:
    result = await open_next_job("missing", _settings())
    assert result.opened is False
    assert "no longer available" in result.reason
