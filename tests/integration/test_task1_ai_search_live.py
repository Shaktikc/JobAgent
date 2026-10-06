"""Opt-in live-browser test for Task 1's "Try AI job search" handling.

It needs no LinkedIn account, no login, and no network: it serves a small
LinkedIn-shaped jobs page from a local HTTP server and drives the **real** Task 1
code path (:func:`_task1_on_page`) in a real Chromium window built by
:func:`build_browser`. This exercises what unit tests cannot: the runtime
``_AI_CANDIDATES_QUERY`` scan, CDP element resolution by the marked attribute,
the click, and the re-click loop.

Enable it (the ``browser`` extra must be installed)::

    uv sync --extra browser
    uvx playwright install chromium
    $env:AUTOJOB_TASK1_LIVE="1"
    uv run pytest tests/integration/test_task1_ai_search_live.py -s

Watch it with the window shown::

    $env:AUTOJOB_TASK1_LIVE="1"
    $env:AUTOJOB_SESSION_HEADLESS="false"
    uv run pytest tests/integration/test_task1_ai_search_live.py -s

Skipped by default so the unit suite stays offline.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from src.configuration import SessionSettings, Settings
from src.tools import browser as browser_tools

pytest.importorskip("browser_use")

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("AUTOJOB_TASK1_LIVE"),
        reason="set AUTOJOB_TASK1_LIVE=1 to run the live Task 1 browser test",
    ),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]


# A LinkedIn-shaped jobs page:
# - a global nav so ``is_logged_in`` returns true without a login gate;
# - the jobs search bar (input + submit);
# - a "Try AI job search" button that disappears after two clicks (so the
#   re-click loop is exercised and then stops on its own);
# - job result cards so ``results_found`` is true;
# - an "Easy Apply filter." toggle.
_PAGE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Jobs</title></head>
<body>
<nav class="global-nav"></nav>
<div class="jobs-search-box">
  <input class="jobs-search-box__keyboard-text-input"
         aria-label="Search by title, skill, or company">
  <button class="jobs-search-box__submit-button" type="button">Search</button>
</div>
<button id="ai-search" type="button" aria-label="Try AI job search">Try AI job search</button>
<button id="easy-apply-filter" type="button" aria-label="Easy Apply filter.">
  Easy Apply filter.
</button>
<ul class="jobs-search__results-list">
  <li class="jobs-search-results__list-item">Backend Engineer</li>
  <li class="jobs-search-results__list-item">Data Engineer</li>
</ul>
<script>
  window.__submitClicks = 0;
  window.__aiClicks = 0;
  document.querySelector('.jobs-search-box__submit-button').addEventListener('click', function () {
    window.__submitClicks += 1;
  });
  var aiLeft = 2;
  document.getElementById('ai-search').addEventListener('click', function () {
    window.__aiClicks += 1;
    aiLeft -= 1;
    if (aiLeft <= 0) { this.remove(); }
  });
  document.getElementById('easy-apply-filter').addEventListener('click', function () {
    this.setAttribute('aria-pressed', 'true');
  });
</script>
</body></html>
"""

_READ_STATE_JS = """() => JSON.stringify({
  ai_clicks: window.__aiClicks,
  submit_clicks: window.__submitClicks,
  filter_pressed: document.getElementById('easy-apply-filter').getAttribute('aria-pressed')
})"""

class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # noqa: ANN002 - silence request noise
        pass


def _serve(directory: Path, filename: str) -> tuple[ThreadingHTTPServer, str]:
    handler = lambda *a, **k: _QuietHandler(*a, directory=str(directory), **k)  # noqa: E731
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/{filename}"
    return server, url


def _settings(tmp_path: Path) -> Settings:
    headless = os.environ.get("AUTOJOB_SESSION_HEADLESS", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    return Settings(
        session=SessionSettings(
            headless=headless,
            post_click_wait_seconds=0.0,
            # The fixture removes the button after two clicks; keep the wait short.
            ai_search_timeout_seconds=0.5,
            ask_human=False,
        ),
        data_dir=tmp_path / "data",
    )


async def test_task1_clicks_ai_job_search_repeatedly(tmp_path: Path) -> None:
    page_file = tmp_path / "task1.html"
    page_file.write_text(_PAGE_HTML, encoding="utf-8")
    server, url = _serve(tmp_path, "task1.html")

    browser = browser_tools.build_browser(_settings(tmp_path))
    try:
        await browser.start()
        page = await browser.new_page()
        # ``_task1_on_page`` performs the initial navigation itself.
        outcome = await browser_tools._task1_on_page(
            page, url, "software engineer", _settings(tmp_path), lambda _m: None
        )
        observed = json.loads(await page.evaluate(_READ_STATE_JS))
    finally:
        await browser.kill()
        server.shutdown()

    # Login gate is satisfied by the fixture's global nav.
    assert outcome.logged_in is True
    assert outcome.results_found is True

    # The AI button was found and clicked, and the loop re-clicked it after each
    # repeated search until it removed itself (two clicks) and then stopped.
    assert outcome.ai_job_search_present is True
    assert outcome.ai_job_search_clicked is True
    assert outcome.ai_job_search_clicks == 2
    assert observed["ai_clicks"] == 2

    # One initial search plus one repeat per click.
    assert observed["submit_clicks"] == 3
    assert outcome.results_count == 2

    # The Easy Apply filter was still selected afterwards.
    assert outcome.easy_apply_filter_selected is True
    assert observed["filter_pressed"] == "true"


# Reproduces the real LinkedIn flow from the screenshot: clicking "Try AI job
# search" replaces the standard jobs page with LinkedIn's AI search page, whose
# only input is the "Describe the job you want" prompt. The repeat search must
# recognise that prompt, type the query into it, and submit with Enter.
_AI_PAGE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Jobs</title></head>
<body>
<nav class="global-nav"></nav>
<div class="jobs-search-box">
  <input class="jobs-search-box__keyboard-text-input"
         aria-label="Search by title, skill, or company">
  <button class="jobs-search-box__submit-button" type="button">Search</button>
</div>
<button id="ai-search" type="button" aria-label="Try AI job search">Try AI job search</button>
<ul class="jobs-search__results-list">
  <li class="jobs-search-results__list-item">Backend Engineer</li>
  <li class="jobs-search-results__list-item">Data Engineer</li>
</ul>
<script>
  window.__submitClicks = 0;
  window.__aiClicks = 0;
  window.__aiSubmits = 0;
  window.__aiPromptValue = '';
  document.querySelector('.jobs-search-box__submit-button').addEventListener('click', function () {
    window.__submitClicks += 1;
  });
  document.getElementById('ai-search').addEventListener('click', function () {
    window.__aiClicks += 1;
    // The AI entry point swaps in the AI search page (as in the real screenshot).
    document.body.innerHTML = ''
      + '<nav class="global-nav"></nav>'
      + '<input id="ai-prompt" aria-label="Describe the job you want" '
      + 'placeholder="Describe the job you want">'
      + '<ul class="jobs-search__results-list" id="ai-results" style="display:none"></ul>'
      + '<button id="easy-apply-filter" type="button" aria-label="Easy Apply filter.">'
      + 'Easy Apply filter.</button>';
    var prompt = document.getElementById('ai-prompt');
    prompt.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter') { return; }
      window.__aiSubmits += 1;
      window.__aiPromptValue = prompt.value;
      var results = document.getElementById('ai-results');
      results.style.display = 'block';
      results.innerHTML = '<li class="jobs-search-results__list-item">Backend Engineer</li>'
        + '<li class="jobs-search-results__list-item">Data Engineer</li>';
    });
    document.getElementById('easy-apply-filter').addEventListener('click', function () {
      this.setAttribute('aria-pressed', 'true');
    });
  });
</script>
</body></html>
"""

_READ_AI_PAGE_JS = """() => JSON.stringify({
  ai_clicks: window.__aiClicks,
  ai_submits: window.__aiSubmits,
  ai_prompt_value: window.__aiPromptValue,
  prompt_present: !!document.getElementById('ai-prompt'),
  filter_pressed: (() => {
    const f = document.getElementById('easy-apply-filter');
    return f ? f.getAttribute('aria-pressed') : null;
  })()
})"""


async def test_task1_searches_via_the_ai_prompt_after_the_ai_click(tmp_path: Path) -> None:
    page_file = tmp_path / "ai_page.html"
    page_file.write_text(_AI_PAGE_HTML, encoding="utf-8")
    server, url = _serve(tmp_path, "ai_page.html")

    browser = browser_tools.build_browser(_settings(tmp_path))
    try:
        await browser.start()
        page = await browser.new_page()
        outcome = await browser_tools._task1_on_page(
            page, url, "software engineer", _settings(tmp_path), lambda _m: None
        )
        observed = json.loads(await page.evaluate(_READ_AI_PAGE_JS))
    finally:
        await browser.kill()
        server.shutdown()

    # The AI button was clicked once, then the repeat search came from the AI
    # prompt ("Describe the job you want"), which the agent now recognises.
    assert outcome.ai_job_search_present is True
    assert outcome.ai_job_search_clicked is True
    assert outcome.ai_job_search_clicks == 1
    assert observed["ai_clicks"] == 1
    assert observed["ai_submits"] == 1
    assert observed["ai_prompt_value"] == "software engineer"

    # Results were found after the AI search and the Easy Apply filter selected.
    assert outcome.results_found is True
    assert outcome.results_count == 2
    assert outcome.easy_apply_filter_selected is True
    assert observed["filter_pressed"] == "true"


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

    monkeypatch.setattr(browser_tools, "build_jobs_search_url", _fail_on_classic)
    # Keep the "wait for results" polls short so the test stays fast.
    monkeypatch.setattr(browser_tools, "_RESULTS_WAIT_SECONDS", 0.5)

    browser = browser_tools.build_browser(_settings(tmp_path))
    try:
        await browser.start()
        page = await browser.new_page()
        outcome = await browser_tools._task1_on_page(
            page, url, "software engineer", _settings(tmp_path), lambda _m: None
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


# Reproduces the filter-selection bug from the screenshot: the results page shows a
# filter pill labelled "Easy Apply" (a toggle) next to the blue "Easy Apply" apply
# button on a job. Both read "Easy Apply"; the agent must click the filter pill,
# never the blue apply button.
_PAGE_FILTER_PILL_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Jobs</title></head>
<body>
<nav class="global-nav"></nav>
<div class="jobs-search-box">
  <input class="jobs-search-box__keyboard-text-input"
         aria-label="Search by title, skill, or company">
  <button class="jobs-search-box__submit-button" type="button">Search</button>
</div>
<button id="easy-apply-pill" type="button" aria-label="Easy Apply" aria-pressed="false">
  Easy Apply
</button>
<button id="easy-apply-blue" type="button" class="jobs-apply-button">Easy Apply</button>
<ul class="jobs-search__results-list">
  <li class="jobs-search-results__list-item">Backend Engineer</li>
  <li class="jobs-search-results__list-item">Data Engineer</li>
</ul>
<script>
  window.__pillClicks = 0;
  window.__blueClicks = 0;
  document.getElementById('easy-apply-pill').addEventListener('click', function () {
    window.__pillClicks += 1;
    this.setAttribute('aria-pressed', 'true');
  });
  document.getElementById('easy-apply-blue').addEventListener('click', function () {
    window.__blueClicks += 1;
  });
</script>
</body></html>
"""

_READ_FILTER_PILL_JS = """() => JSON.stringify({
  pill_pressed: document.getElementById('easy-apply-pill').getAttribute('aria-pressed'),
  pill_clicks: window.__pillClicks,
  blue_clicks: window.__blueClicks
})"""


async def test_task1_clicks_the_easy_apply_filter_pill_not_the_apply_button(
    tmp_path: Path,
) -> None:
    page_file = tmp_path / "filter_pill.html"
    page_file.write_text(_PAGE_FILTER_PILL_HTML, encoding="utf-8")
    server, url = _serve(tmp_path, "filter_pill.html")

    browser = browser_tools.build_browser(_settings(tmp_path))
    try:
        await browser.start()
        page = await browser.new_page()
        outcome = await browser_tools._task1_on_page(
            page, url, "software engineer", _settings(tmp_path), lambda _m: None
        )
        observed = json.loads(await page.evaluate(_READ_FILTER_PILL_JS))
    finally:
        await browser.kill()
        server.shutdown()

    assert outcome.results_found is True
    # The Easy Apply filter was selected by clicking the pill toggle.
    assert outcome.easy_apply_filter_selected is True
    assert observed["pill_pressed"] == "true"
    assert observed["pill_clicks"] == 1
    # The blue "Easy Apply" apply button on the job was never clicked.
    assert observed["blue_clicks"] == 0


