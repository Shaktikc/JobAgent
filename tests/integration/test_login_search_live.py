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


async def test_task1_logs_in_searches_and_selects_easy_apply() -> None:
    from src.tools.browser import run_task1

    outcome = await run_task1(LIVE_URL, "software engineer", progress=print)

    assert outcome.logged_in, "login was not completed"
    assert outcome.results_found, f"no search results (url={outcome.page_url})"
    assert outcome.easy_apply_filter_selected, "Easy Apply filter was not selected"
