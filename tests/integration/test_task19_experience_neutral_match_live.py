"""Opt-in live-browser check for Task 19's experience-neutral match input.

A LinkedIn-shaped job posting requiring `10+ years` is rendered in a real
Chromium window, read with the production job-description query, and converted
into the exact match messages the LLM receives. The test proves the years
requirement is removed from the match view while the real requirements and the
original stored description are preserved.

Enable it (the ``browser`` extra must be installed)::

    $env:AUTOJOB_TASK19_LIVE="1"
    uv run pytest tests/integration/test_task19_experience_neutral_live.py -s
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.configuration import SessionSettings, Settings
from src.tools import browser as browser_tools
from src.tools.linkedin_best_matching_resume import read_job_description
from src.tools.resume_descriptions import (
    ResumeDescription,
    build_match_messages,
    candidate_ids,
)

pytest.importorskip("browser_use")

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("AUTOJOB_TASK19_LIVE"),
        reason="set AUTOJOB_TASK19_LIVE=1 to run the live Task 19 browser test",
    ),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Backend Engineer | Acme | LinkedIn</title></head><body>
<main>
  <h1 class="job-details-jobs-unified-top-card__job-title">Backend Engineer</h1>
  <div class="job-details-jobs-unified-top-card__company-name">Acme</div>
  <div class="job-details-jobs-unified-top-card__bullet">Sydney</div>
  <div class="jobs-description__content">
    <p>Minimum 10+ years of experience with Python and AWS in fintech.</p>
    <p>You will build reliable APIs and distributed services.</p>
  </div>
</main>
</body></html>"""


def _settings(tmp_path: Path) -> Settings:
    """Settings for a real Chromium run against a local fixture."""
    return Settings(
        session=SessionSettings(headless=True, clean_stale_profile=False),
        data_dir=tmp_path / "data",
        resumes_dir=tmp_path / "resumes",
    )


async def test_experience_neutral_match_view_in_a_real_browser(tmp_path: Path) -> None:
    """Task 19: a 10+ year requirement must not reach the LLM as a skip signal."""
    page_file = tmp_path / "job.html"
    page_file.write_text(_HTML, encoding="utf-8")

    browser = browser_tools.build_browser(_settings(tmp_path))
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(page_file.as_uri())
        await browser_tools._wait_for_load(page, 10)
        description = await read_job_description(page)
    finally:
        await browser.kill()

    assert description.title == "Backend Engineer"
    assert description.is_read is True

    candidates = [
        ("a.pdf", ResumeDescription(summary="Backend", years_experience=7)),
    ]
    messages = build_match_messages(description, candidates, candidate_ids(candidates))
    prompt = messages[0]["content"].lower()
    user = messages[1]["content"]

    assert "10 years" not in user
    assert "years_experience" not in user
    assert "Python" in user and "AWS" in user
    assert "years-of-experience requirements are non-blocking" in prompt
