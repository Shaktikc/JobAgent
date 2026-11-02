"""Opt-in live-browser test for Task 4: fill the Easy Apply form, never submit.

Unlike ``test_login_search_live`` this needs no LinkedIn account, no login, and
no network. It serves a self-contained two-step Easy Apply fixture from a local
file and drives the **real** Task 4 code path (:func:`_task4_on_page`) in a real
Chromium window built by :func:`build_browser`.

Enable it (the ``browser`` extra must be installed)::

    uv sync --extra browser
    uvx playwright install chromium
    $env:AUTOJOB_FILL_LIVE="1"
    uv run pytest tests/integration/test_fill_form_live -s

Watch it in **slow mode** so each visible step pauses::

    $env:AUTOJOB_FILL_LIVE="1"
    $env:AUTOJOB_SESSION_HEADLESS="false"     # show the window
    $env:AUTOJOB_FILL_TEST_STEP_DELAY="2"     # seconds between visible steps
    uv run pytest tests/integration/test_fill_form_live -s

Skipped by default (no browser extra / flag unset) so the unit suite stays fast.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.configuration import SessionSettings, Settings
from src.tools.answers import normalize_question
from src.tools.llm_answers import QuestionDecision

pytest.importorskip("browser_use")


def _store_chooser(answers: dict):
    """Stand in for the Task 4.1 LLM so the live tests never hit the network."""

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

_RESUME_NAME = "ShaktiKC_Resume_python_Node_Senior.txt"

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("AUTOJOB_FILL_LIVE"),
        reason="set AUTOJOB_FILL_LIVE=1 to run the live Task 4 browser test",
    ),
    # browser-use's Chromium subprocess leaves a ProactorEventLoop pipe transport
    # for GC after the session is killed; on Windows it is torn down after the
    # loop closes, raising a harmless ResourceWarning. Scope it here so it cannot
    # mask unrelated warnings elsewhere.
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]


def _settings(tmp_path: Path, *, ask_human: bool = False) -> Settings:
    """Browser settings; slow motion + visibility are env-controlled.

    Task 5's browser prompt is off unless a test supplies a (simulated) human.
    """
    delay = float(os.environ.get("AUTOJOB_FILL_TEST_STEP_DELAY", "0"))
    headless = os.environ.get("AUTOJOB_SESSION_HEADLESS", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    return Settings(
        session=SessionSettings(
            headless=headless,
            step_delay_seconds=delay,
            post_click_wait_seconds=0.0,
            ask_human=ask_human,
            ask_timeout_seconds=30.0,
            ask_poll_seconds=0.1,
        ),
        data_dir=tmp_path / "data",
    )


_ANSWERS = {
    "phone number": "+61 400 000 000",
    "are you authorised to work in australia": "Yes",
    "years of experience": "5",
}
