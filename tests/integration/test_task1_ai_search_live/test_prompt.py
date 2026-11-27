from __future__ import annotations

import json
from pathlib import Path

from src.state import DEFAULT_SEARCH_QUERY
from src.tools import browser as browser_tools

from .common import _render, _serve, _settings
from .common import pytestmark as pytestmark

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
<!--DATE_FILTER-->
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
    var dateFilter = document.getElementById('date-posted-wrap').outerHTML;
    // The AI entry point swaps in the AI search page (as in the real screenshot).
    document.body.innerHTML = ''
      + '<nav class="global-nav"></nav>'
      + '<input id="ai-prompt" aria-label="Describe the job you want" '
      + 'placeholder="Describe the job you want">'
      + '<ul class="jobs-search__results-list" id="ai-results" style="display:none"></ul>'
      + '<button id="easy-apply-filter" type="button" aria-label="Easy Apply filter.">'
      + 'Easy Apply filter.</button>'
      + dateFilter;
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
  //DATE_FILTER_JS
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
    page_file.write_text(_render(_AI_PAGE_HTML), encoding="utf-8")
    server, url = _serve(tmp_path, "ai_page.html")

    browser = browser_tools.build_browser(_settings(tmp_path))
    try:
        await browser.start()
        page = await browser.new_page()
        outcome = await browser_tools._task1_on_page(
            page, url, DEFAULT_SEARCH_QUERY, _settings(tmp_path), lambda _m: None
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
    assert observed["ai_prompt_value"] == DEFAULT_SEARCH_QUERY

    # Results were found after the AI search and the Easy Apply filter selected.
    assert outcome.results_found is True
    assert outcome.results_count == 2
    assert outcome.easy_apply_filter_selected is True
    assert observed["filter_pressed"] == "true"


