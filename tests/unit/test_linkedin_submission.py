"""Unit tests for the post-apply submission probe and rules (BUG-060).

The live run got stuck waiting for a submission the human had already made: the
SDUI confirmation dialog had no role/artdeco hook, the details pane said
"Application submitted", and the card fallback matched a *different*
"Senior Software Engineer" card that was already Applied, so the real card flip
was treated as stale. These tests pin the new signals and the title+company card
match.
"""

from __future__ import annotations

import asyncio
import json

from src.configuration import SessionSettings, Settings
from src.tools import browser as browser_tools
from src.tools import linkedin_apply_loop as loop
from src.tools.linkedin_submission import (
    _submission_query,
    is_dismiss_label,
    looks_like_submission,
    read_submission_state,
    submission_detected,
)


def test_status_panel_detects_a_new_submission() -> None:
    assert submission_detected(
        confirmation="",
        form_open=False,
        card_applied=False,
        status_submitted=True,
    )
    # Already submitted before the wait started: stale, not this submission.
    assert not submission_detected(
        confirmation="",
        form_open=False,
        card_applied=False,
        status_submitted=True,
        status_was_submitted=True,
    )
    # The form is still open, so the pane is not evidence for this attempt.
    assert not submission_detected(
        confirmation="",
        form_open=True,
        card_applied=False,
        status_submitted=True,
    )


def test_confirmation_wins_over_the_stale_baselines() -> None:
    assert submission_detected(
        confirmation="Your application was sent to Acme!",
        form_open=True,
        card_applied=True,
        card_was_applied=True,
        status_submitted=True,
        status_was_submitted=True,
    )


def test_card_flip_still_needs_the_form_closed() -> None:
    assert submission_detected(confirmation="", form_open=False, card_applied=True)
    assert not submission_detected(confirmation="", form_open=True, card_applied=True)
    assert not submission_detected(
        confirmation="", form_open=False, card_applied=True, card_was_applied=True
    )


def test_probe_matches_the_card_by_its_title_line() -> None:
    """A longer title ("Senior Software Engineer") must not be picked for this job."""
    query = _submission_query("Software Engineer", "LEAP Legal Software")
    assert '"Software Engineer"' in query
    assert "headOf(c) === wanted" in query
    assert "headOf(c) === wanted && (!company || text.includes(company))" in query
    assert "text.includes(wanted)" not in query


def test_probe_reads_the_sdui_dialog_and_the_status_panel() -> None:
    query = _submission_query("Software Engineer", "Acme")
    # Native <dialog>/overlay markup without artdeco hooks (the live failure).
    assert "dialog, div[role=\"dialog\"], [role=\"alertdialog\"], [aria-modal=\"true\"]" in query
    assert "status_submitted" in query
    assert "application submitted" in query


def test_probe_never_treats_a_confirmation_dialog_as_the_open_form() -> None:
    query = _submission_query("Software Engineer", "Acme")
    assert "const formOpen = !!form && !confirmRe.test(norm(form.innerText));" in query


def test_dismiss_and_confirmation_helpers_are_unchanged() -> None:
    assert is_dismiss_label("Not now")
    assert not is_dismiss_label("Update profile")
    assert looks_like_submission("Your application was sent to Acme")
    assert not looks_like_submission("Applied · Easy Apply")


class _FakePage:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.query = ""

    async def evaluate(self, js: str, *args):
        self.query = js
        return json.dumps(self.payload)


async def test_read_submission_state_maps_the_status_signal() -> None:
    page = _FakePage(
        {
            "form_open": False,
            "confirmation": "",
            "card_applied": True,
            "status_submitted": True,
            "done_marker": "d0",
        }
    )

    state = await read_submission_state(page, "Software Engineer", "LEAP Legal Software")

    assert state == {
        "form_open": False,
        "confirmation": "",
        "card_applied": True,
        "status_submitted": True,
        "done_marker": "d0",
    }
    assert '"LEAP Legal Software"' in page.query


class _DeadPage:
    """A page whose CDP link is gone: ``evaluate`` never returns."""

    async def evaluate(self, js: str, *args):
        await asyncio.sleep(3600)


class _StubSession:
    is_cdp_connected = True

    async def stop(self) -> None:
        pass


async def test_await_human_submit_ends_when_the_page_stops_responding(monkeypatch) -> None:
    """BUG-061: a dead browser must end the wait instead of blocking forever."""
    run_id = "run-dead"
    browser_tools._ACTIVE_RUNS[run_id] = browser_tools._Run(
        session=_StubSession(), page=_DeadPage()
    )
    monkeypatch.setattr(loop, "_READ_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(loop, "_MAX_UNRESPONSIVE_READS", 2)
    settings = Settings(
        session=SessionSettings(
            keep_open_timeout_seconds=30.0, keep_open_poll_seconds=0.01
        )
    )
    try:
        result = await asyncio.wait_for(loop.await_human_submit(run_id, settings), 2)
    finally:
        browser_tools._ACTIVE_RUNS.pop(run_id, None)

    assert result == "closed"
