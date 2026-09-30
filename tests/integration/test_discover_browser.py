"""Manual integration smoke for `discovery` via browser-use (Task 5/17).

Requires a real browser, a human-logged-in LinkedIn session in ``data/profile``,
and an OpenRouter key + model. It reads **one real Easy Apply job URL** and asserts
the agent's read is non-empty. It never fills or submits anything.

Set the environment, then run::

    $env:AUTOJOB_TEST_JOB_URL = "https://www.linkedin.com/jobs/view/<id>/"
    $env:OPENROUTER_API_KEY = "..."
    $env:AUTOJOB_LLM_MODEL = "anthropic/claude-sonnet-4-6"
    poetry run pytest -m integration tests/integration/test_discover_browser.py

Skipped automatically when the URL or the model is unset.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from src.configuration import AppSettings
from src.nodes import discover
from src.tools import browser
from src.tools.browser_agent import build_openrouter_llm

pytestmark = pytest.mark.integration


@pytest.fixture
def job_url() -> str:
    url = os.environ.get("AUTOJOB_TEST_JOB_URL")
    if not url:
        pytest.skip("set AUTOJOB_TEST_JOB_URL to a real Easy Apply job URL")
    return url


def test_read_real_easy_apply_job(job_url: str) -> None:
    settings = AppSettings.from_env()
    if not settings.llm.model:
        pytest.skip("set AUTOJOB_LLM_MODEL to run the browser-use read")
    settings.paths.ensure_runtime_dirs()

    async def go() -> dict:
        async with browser.browser_session(settings) as session:
            llm = build_openrouter_llm(settings.llm.model or "")
            state = await discover.read_job(session, llm, job_url)
        return state

    state = asyncio.run(go())

    assert state["easy_apply"] is True
    assert state["job_id"]
    assert state["title"]
    assert state["company"]
    assert state["description"]
