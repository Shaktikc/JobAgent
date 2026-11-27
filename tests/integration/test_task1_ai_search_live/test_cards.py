from __future__ import annotations

import json
from pathlib import Path

from src.state import DEFAULT_SEARCH_QUERY
from src.tools import browser as browser_tools

from .common import _render, _serve, _settings
from .common import pytestmark as pytestmark

# Reproduces the real AI/semantic results page: after clicking "Try AI job
# search", LinkedIn swaps in its AI search mode where the job cards are rendered
# as div[role="button"] (not the classic <li> items). The repeat search must
# recognise those cards so the run proceeds promptly (it must not stall waiting
# for classic cards that never appear) and the Easy Apply filter is selected.
_PAGE_AI_DIV_CARDS_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Jobs</title></head>
<body>
<nav class="global-nav"></nav>
<div class="jobs-search-box">
  <input class="jobs-search-box__keyboard-text-input"
         aria-label="Search by title, skill, or company">
  <button class="jobs-search-box__submit-button" type="button">Search</button>
</div>
<button id="ai-search" type="button" aria-label="Try AI job search">Try AI job search</button>
<button id="searchFilter_applyWithLinkedin" type="button" role="radio"
        aria-checked="false" aria-label="Easy Apply filter.">Easy Apply</button>
<!--DATE_FILTER-->
<ul class="jobs-search__results-list">
  <li class="jobs-search-results__list-item">Backend Engineer</li>
  <li class="jobs-search-results__list-item">Data Engineer</li>
</ul>
<script>
  window.__aiClicks = 0;
  window.__aiSubmits = 0;
  window.__pillClicks = 0;
  document.getElementById('ai-search').addEventListener('click', function () {
    window.__aiClicks += 1;
    var dateFilter = document.getElementById('date-posted-wrap').outerHTML;
    // LinkedIn's AI search mode: the classic cards are gone, and the new cards
    // are div[role="button"], not <li> items.
    document.body.innerHTML = ''
      + '<nav class="global-nav"></nav>'
      + '<input id="ai-prompt" aria-label="Describe the job you want" '
      + 'placeholder="Describe the job you want">'
      + '<button id="searchFilter_applyWithLinkedin" type="button" role="radio" '
      + 'aria-checked="false" aria-label="Easy Apply filter.">Easy Apply</button>'
      + '<div role="button" class="jobcard">Senior Software Engineer Care GP '
      + 'Sydney, NSW (On-site) Actively reviewing applicants Viewed Posted '
      + '3 weeks ago</div>'
      + '<div role="button" class="jobcard">Full Stack Engineer MoreGoodDays '
      + 'Australia (Remote) Actively reviewing applicants Posted 1 week ago</div>'
      + dateFilter;
    var prompt = document.getElementById('ai-prompt');
    prompt.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') { return; }
      window.__aiSubmits += 1;
    });
    document.getElementById('searchFilter_applyWithLinkedin')
      .addEventListener('click', function () {
        window.__pillClicks += 1;
        this.setAttribute('aria-checked', 'true');
      });
  });
  //DATE_FILTER_JS
</script>
</body></html>
"""

_READ_AI_DIV_JS = """() => JSON.stringify({
  ai_clicks: window.__aiClicks,
  ai_submits: window.__aiSubmits,
  pill_checked: document.getElementById('searchFilter_applyWithLinkedin')
    .getAttribute('aria-checked'),
  pill_clicks: window.__pillClicks,
  div_cards: document.querySelectorAll('div[role="button"]').length
})"""


async def test_task1_detects_ai_div_job_cards_and_selects_filter(tmp_path: Path) -> None:
    page_file = tmp_path / "ai_div_cards.html"
    page_file.write_text(_render(_PAGE_AI_DIV_CARDS_HTML), encoding="utf-8")
    server, url = _serve(tmp_path, "ai_div_cards.html")

    browser = browser_tools.build_browser(_settings(tmp_path))
    try:
        await browser.start()
        page = await browser.new_page()
        outcome = await browser_tools._task1_on_page(
            page, url, DEFAULT_SEARCH_QUERY, _settings(tmp_path), lambda _m: None
        )
        observed = json.loads(await page.evaluate(_READ_AI_DIV_JS))
    finally:
        await browser.kill()
        server.shutdown()

    assert outcome.ai_job_search_clicked is True
    assert outcome.ai_job_search_clicks == 1
    # The repeat search recognised the div[role="button"] cards, so results were
    # found (the run did not stall waiting for classic <li> cards).
    assert outcome.results_found is True
    assert outcome.results_count == 2
    # The Easy Apply filter pill (beside Backend) was clicked.
    assert outcome.easy_apply_filter_selected is True
    assert observed["div_cards"] == 2
    assert observed["pill_checked"] == "true"
    assert observed["pill_clicks"] == 1


