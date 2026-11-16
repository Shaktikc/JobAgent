from __future__ import annotations

import json
from pathlib import Path

from src.tools import browser as browser_tools

from .common import _render, _serve, _settings
from .common import pytestmark as pytestmark

# Reproduces the filter-selection bug from the screenshot: the results page shows a
# filter pill labelled "Easy Apply" (role="radio" / aria-checked) next to the blue
# "Easy Apply" apply button on a job. Both mention "Easy Apply"; the agent must click
# the filter pill, never the blue apply button. Markup copied from the real page.
_PAGE_FILTER_PILL_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Jobs</title></head>
<body>
<nav class="global-nav"></nav>
<div class="jobs-search-box">
  <input class="jobs-search-box__keyboard-text-input"
         aria-label="Search by title, skill, or company">
  <button class="jobs-search-box__submit-button" type="button">Search</button>
</div>
<button id="searchFilter_applyWithLinkedin" type="button" role="radio"
        aria-checked="false" aria-label="Easy Apply filter."
        class="artdeco-pill artdeco-pill--choice search-reusables__filter-pill-button">
  Easy Apply
</button>
<button id="jobs-apply-button-id" type="button" aria-label="Easy Apply to Backend Engineer at Acme"
        class="jobs-apply-button artdeco-button artdeco-button--primary ember-view"
        data-live-test-job-apply-button="">Easy Apply</button>
<!--DATE_FILTER-->
<ul class="jobs-search__results-list">
  <li class="jobs-search-results__list-item">Backend Engineer</li>
  <li class="jobs-search-results__list-item">Data Engineer</li>
</ul>
<script>
  window.__pillClicks = 0;
  window.__blueClicks = 0;
  document.getElementById('searchFilter_applyWithLinkedin').addEventListener('click', function () {
    window.__pillClicks += 1;
    this.setAttribute('aria-checked', 'true');
  });
  document.getElementById('jobs-apply-button-id').addEventListener('click', function () {
    window.__blueClicks += 1;
  });
  //DATE_FILTER_JS
</script>
</body></html>
"""

_READ_FILTER_PILL_JS = """() => JSON.stringify({
  pill_checked: document.getElementById(
    'searchFilter_applyWithLinkedin'
  ).getAttribute('aria-checked'),
  pill_clicks: window.__pillClicks,
  blue_clicks: window.__blueClicks
})"""


async def test_task1_clicks_the_easy_apply_filter_pill_not_the_apply_button(
    tmp_path: Path,
) -> None:
    page_file = tmp_path / "filter_pill.html"
    page_file.write_text(_render(_PAGE_FILTER_PILL_HTML), encoding="utf-8")
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
    assert observed["pill_checked"] == "true"
    assert observed["pill_clicks"] == 1
    # The blue "Easy Apply" apply button on the job was never clicked.
    assert observed["blue_clicks"] == 0


