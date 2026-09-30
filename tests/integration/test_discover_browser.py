"""Manual integration smoke for partial `discovery` (Task 5).

Requires a real browser and a human-logged-in LinkedIn session in
``data/profile``. It reads **one real Easy Apply job URL** and asserts the parsed
fields are non-empty. It never fills or submits anything.

Set the URL (see the board's T5 Review card), then run::

    $env:AUTOJOB_TEST_JOB_URL = "https://www.linkedin.com/jobs/view/<id>/"
    poetry run pytest -m integration tests/integration/test_discover_browser.py

Skipped automatically when ``AUTOJOB_TEST_JOB_URL`` is unset.
"""

from __future__ import annotations

import os

import pytest

from src.configuration import AppSettings
from src.nodes import discover
from src.tools import browser

pytestmark = pytest.mark.integration


@pytest.fixture
def job_url() -> str:
    url = os.environ.get("AUTOJOB_TEST_JOB_URL")
    if not url:
        pytest.skip("set AUTOJOB_TEST_JOB_URL to a real Easy Apply job URL")
    return url


def test_read_real_easy_apply_job(job_url: str) -> None:
    settings = AppSettings.from_env()
    settings.paths.ensure_runtime_dirs()

    with browser.browser_context(settings) as context:
        page = context.pages[0] if context.pages else context.new_page()
        state = discover.read_job(page, job_url)

    assert state["easy_apply"] is True
    assert state["job_id"]
    assert state["title"]
    assert state["company"]
    assert state["description"]
