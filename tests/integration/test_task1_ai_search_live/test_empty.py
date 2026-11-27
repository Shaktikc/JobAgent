from __future__ import annotations

from pathlib import Path

import pytest

from src.state import DEFAULT_SEARCH_QUERY
from src.tools import browser as browser_tools
from src.tools import linkedin_search as linkedin_tools

from .common import _serve, _settings
from .common import pytestmark as pytestmark

# Reproduces the real failure: clicking "Try AI job search" switches the page into
# Reproduces the real failure: clicking "Try AI job search" switches the page into
# LinkedIn's semantic mode, which renders **no** job cards, so the repeat search
# returns nothing. Once the AI control has been clicked the run must stay in the
# AI mode and never fall back to the classic jobs search.
_PAGE_AI_EMPTY_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Jobs</title></head>
<body>
<nav class="global-nav"></nav>
<div class="jobs-search-box">
  <input class="jobs-search-box__keyboard-text-input"
         aria-label="Search by title, skill, or company">
  <button class="jobs-search-box__submit-button" type="button">Search</button>
</div>
<button id="ai-search" type="button" aria-label="Try AI job search">Try AI job search</button>
<ul class="jobs-search__results-list" id="results">
  <li class="jobs-search-results__list-item">Backend Engineer</li>
  <li class="jobs-search-results__list-item">Data Engineer</li>
</ul>
<script>
  window.__aiClicks = 0;
  document.getElementById('ai-search').addEventListener('click', function () {
    window.__aiClicks += 1;
    // LinkedIn's semantic mode: the classic job cards are gone.
    var results = document.getElementById('results');
    if (results) { results.remove(); }
    this.remove();
  });
</script>
</body></html>
"""


async def test_task1_stays_in_ai_mode_when_the_detour_is_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    page_file = tmp_path / "ai_empty.html"
    page_file.write_text(_PAGE_AI_EMPTY_HTML, encoding="utf-8")
    server, url = _serve(tmp_path, "ai_empty.html")

    # Fail loudly if the agent tries to fall back to the classic search URL.
    def _fail_on_classic(_query: str) -> str:
        raise AssertionError("fell back to the classic jobs search URL")

    monkeypatch.setattr(linkedin_tools.search_box, "build_jobs_search_url", _fail_on_classic)
    # Keep the "wait for results" polls short so the test stays fast.
    monkeypatch.setattr(linkedin_tools.search_box, "_RESULTS_WAIT_SECONDS", 0.5)

    browser = browser_tools.build_browser(_settings(tmp_path))
    try:
        await browser.start()
        page = await browser.new_page()
        outcome = await browser_tools._task1_on_page(
            page, url, DEFAULT_SEARCH_QUERY, _settings(tmp_path), lambda _m: None
        )
    finally:
        await browser.kill()
        server.shutdown()

    assert outcome.ai_job_search_present is True
    assert outcome.ai_job_search_clicked is True
    assert outcome.ai_job_search_clicks == 1
    # The AI mode left no cards and the run stayed in AI mode (no classic fallback).
    assert outcome.results_found is False
    assert outcome.results_count == 0
    assert not hasattr(outcome, "search_restored")


