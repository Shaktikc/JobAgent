"""Opt-in integration test that drives a real browser against LinkedIn.

It needs a human to complete the login gate. Enable it by installing the browser
extra and pointing at the login URL:

    uv sync --extra browser
    uvx playwright install chromium

    $env:AUTOJOB_LIVE_URL="https://www.linkedin.com/login/"
    uv run pytest tests/integration

Skipped by default so the unit suite stays offline.
"""

from __future__ import annotations

import os

import pytest

LIVE_URL = os.environ.get("AUTOJOB_LIVE_URL")

pytestmark = pytest.mark.skipif(
    not LIVE_URL,
    reason="set AUTOJOB_LIVE_URL to run the live browser test",
)


async def test_agent_runs_tasks_1_to_4_without_submitting() -> None:
    from src.tools.browser import run_full_agent

    result = await run_full_agent(LIVE_URL, "software engineer", progress=print)

    assert result.task1.logged_in, "login was not completed"
    assert result.task1.results_found, f"no search results (url={result.task1.page_url})"
    assert result.task1.easy_apply_filter_selected, "Easy Apply filter was not selected"

    assert result.task2.easy_apply_clicked, (
        f"no Easy Apply button was clicked (url={result.task2.page_url})"
    )
    assert result.task2.application_form_opened, "Easy Apply form did not open"

    assert result.job_description.is_read, "job description was not read"

    # Task 3/4 depend on the local resumes/ and answers store; the form must at
    # least be found and the application must never be submitted.
    assert result.task4.form_open, "Easy Apply form fields were not found"
    assert result.task4.submitted is False, "the application must never be submitted"
