"""Opt-in live-browser test for Task 13's **Date posted** filter.

It needs no LinkedIn account and no network: it serves a LinkedIn-shaped jobs
results page from a local HTTP server and drives the **real** Task 1 code path
(:func:`_task1_on_page`) in a real Chromium window. This exercises what the unit
tests cannot: the runtime ``_DATE_FILTER_QUERY``/``_DATE_OPTIONS_QUERY`` scans,
CDP element resolution by marker, clicking the native radios, **Show results**,
and verifying the resulting ``f_TPR=r86400`` URL.

Enable it (the ``browser`` extra must be installed)::

    uv sync --extra browser
    uvx playwright install chromium
    $env:AUTOJOB_TASK13_LIVE="1"
    uv run pytest tests/integration/test_date_posted_live.py -s

Watch it with the window shown::

    $env:AUTOJOB_TASK13_LIVE="1"
    $env:AUTOJOB_SESSION_HEADLESS="false"
    uv run pytest tests/integration/test_date_posted_live.py -s

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
        not os.environ.get("AUTOJOB_TASK13_LIVE"),
        reason="set AUTOJOB_TASK13_LIVE=1 to run the live Date posted test",
    ),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]


# A classic LinkedIn results page: Easy Apply pill, Date posted pill + popover
# (past month/week/24 hours) and a Show results button. One card says
# "Posted 1 day ago" so the agent must not confuse the card with the filter.
# The date selection is applied in place with history.replaceState so the test
# can prove no reload happened (the real page navigates; the verification is the
# same).
_PAGE_HTML = """<!doctype html>
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
<button id="searchFilter_timePostedRange" type="button" role="radio"
        aria-checked="false" aria-label="Date posted filter.">Date posted</button>
<div id="date-posted-popover" style="display:none">
  <label for="tp-month">Past month</label>
  <input type="radio" id="tp-month" name="timePostedRange" value="r2592000">
  <label for="tp-week">Past week</label>
  <input type="radio" id="tp-week" name="timePostedRange" value="r604800">
  <label for="tp-24h">Past 24 hours</label>
  <input type="radio" id="tp-24h" name="timePostedRange" value="r86400">
  <button id="date-posted-show" type="button">Show results</button>
</div>
<ul class="jobs-search__results-list">
  <li class="jobs-search-results__list-item">Backend Engineer</li>
  <li class="jobs-search-results__list-item">Data Engineer</li>
</ul>
<div id="job-card" role="button">Senior Software Engineer Care GP
  Sydney, NSW (On-site) Posted 1 day ago</div>
<script>
  window.__initialMarker = true;
  window.__easyApplyClicks = 0;
  window.__dateFilterClicks = 0;
  window.__showResultsClicks = 0;
  window.__cardClicks = 0;
  document.getElementById('searchFilter_applyWithLinkedin').addEventListener('click', function () {
    window.__easyApplyClicks += 1;
    this.setAttribute('aria-checked', 'true');
  });
  document.getElementById('searchFilter_timePostedRange').addEventListener('click', function () {
    window.__dateFilterClicks += 1;
    var pop = document.getElementById('date-posted-popover');
    pop.style.display = pop.style.display === 'none' ? 'block' : 'none';
  });
  document.getElementById('date-posted-show').addEventListener('click', function () {
    window.__showResultsClicks += 1;
    var checked = document.querySelector('input[name="timePostedRange"]:checked');
    if (checked) {
      var next = new URL(window.location.href);
      next.searchParams.set('f_TPR', checked.value);
      window.history.replaceState({}, '', next.toString());
      document.getElementById('searchFilter_timePostedRange').setAttribute('aria-checked', 'true');
    }
    document.getElementById('date-posted-popover').style.display = 'none';
  });
  document.getElementById('job-card').addEventListener('click', function () {
    window.__cardClicks += 1;
  });
</script>
</body></html>
"""

_READ_STATE_JS = """() => JSON.stringify({
  initial_marker: window.__initialMarker === true,
  easy_apply_clicks: window.__easyApplyClicks,
  date_filter_clicks: window.__dateFilterClicks,
  show_results_clicks: window.__showResultsClicks,
  card_clicks: window.__cardClicks,
  past_24_hours_checked: (() => {
    const input = document.getElementById('tp-24h');
    return !!(input && input.checked);
  })(),
  past_week_checked: (() => {
    const input = document.getElementById('tp-week');
    return !!(input && input.checked);
  })(),
  url: window.location.href
})"""


# The same page without any Date posted control. The run must add f_TPR=r86400
# to the current URL (preserving the query) and then re-select Easy Apply after
# the reload.
_FALLBACK_PAGE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Jobs</title></head>
<body>
<nav class="global-nav"></nav>
<div class="jobs-search-box">
  <input class="jobs-search-box__keyboard-text-input"
         aria-label="Search by title, skill, or company">
  <button class="jobs-search-box__submit-button" type="button">Search</button>
</div>
<button id="searchFilter_applyWithLinkedin" type="button" role="radio"
        aria-checked="false" aria-label="Easy Apply filter.">Easy Apply</button>
<ul class="jobs-search__results-list">
  <li class="jobs-search-results__list-item">Backend Engineer</li>
  <li class="jobs-search-results__list-item">Data Engineer</li>
</ul>
<script>
  window.__easyApplyClicks = 0;
  document.getElementById('searchFilter_applyWithLinkedin').addEventListener('click', function () {
    window.__easyApplyClicks += 1;
    this.setAttribute('aria-checked', 'true');
  });
</script>
</body></html>
"""

_READ_FALLBACK_JS = """() => JSON.stringify({
  easy_apply_clicks: window.__easyApplyClicks,
  url: window.location.href
})"""


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # noqa: ANN002 - silence request noise
        pass


def _serve(directory: Path, filename: str) -> tuple[ThreadingHTTPServer, str]:
    handler = lambda *a, **k: _QuietHandler(*a, directory=str(directory), **k)  # noqa: E731
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
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
            ai_search_timeout_seconds=0.0,
            ask_human=False,
        ),
        data_dir=tmp_path / "data",
    )


async def test_task1_selects_past_24_hours_and_keeps_easy_apply(tmp_path: Path) -> None:
    page_file = tmp_path / "date_posted.html"
    page_file.write_text(_PAGE_HTML, encoding="utf-8")
    server, url = _serve(tmp_path, "date_posted.html")

    browser = browser_tools.build_browser(_settings(tmp_path))
    try:
        await browser.start()
        page = await browser.new_page()
        outcome = await browser_tools._task1_on_page(
            page, url, "software engineer", _settings(tmp_path), lambda _m: None
        )
        observed = json.loads(await page.evaluate(_READ_STATE_JS))
    finally:
        await browser.kill()
        server.shutdown()

    assert outcome.logged_in is True
    assert outcome.results_found is True
    assert outcome.easy_apply_filter_selected is True
    assert outcome.date_posted_filter_selected is True
    assert outcome.date_posted_filter_value == "past_24_hours"
    assert "f_TPR=r86400" in observed["url"]

    # The visible UI path was used: the Date posted pill, the Past 24 hours
    # radio, and Show results were all clicked exactly once.
    assert observed["date_filter_clicks"] == 1
    assert observed["show_results_clicks"] == 1
    assert observed["past_24_hours_checked"] is True

    # The date selection did not reload the page, and the Easy Apply pill stayed
    # selected (no re-click needed).
    assert observed["initial_marker"] is True
    assert observed["easy_apply_clicks"] == 1

    # A job card's "Posted 1 day ago" text is never treated as the filter/option.
    assert observed["card_clicks"] == 0


async def test_task1_selects_the_requested_past_week_range(tmp_path: Path) -> None:
    """Task 17: when the user chooses Past week first, Task 1 applies it."""
    page_file = tmp_path / "date_posted_week.html"
    page_file.write_text(_PAGE_HTML, encoding="utf-8")
    server, url = _serve(tmp_path, "date_posted_week.html")

    browser = browser_tools.build_browser(_settings(tmp_path))
    try:
        await browser.start()
        page = await browser.new_page()
        outcome = await browser_tools._task1_on_page(
            page,
            url,
            "software engineer",
            _settings(tmp_path),
            lambda _m: None,
            date_range="past_week",
        )
        observed = json.loads(await page.evaluate(_READ_STATE_JS))
    finally:
        await browser.kill()
        server.shutdown()

    assert outcome.logged_in is True
    assert outcome.results_found is True
    assert outcome.easy_apply_filter_selected is True
    assert outcome.date_posted_filter_selected is True
    assert outcome.date_posted_filter_value == "past_week"
    assert "f_TPR=r604800" in observed["url"]
    assert observed["date_filter_clicks"] == 1
    assert observed["show_results_clicks"] == 1
    assert observed["past_week_checked"] is True
    assert observed["card_clicks"] == 0


async def test_task1_uses_the_url_fallback_and_rechecks_easy_apply(tmp_path: Path) -> None:
    page_file = tmp_path / "no_date_filter.html"
    page_file.write_text(_FALLBACK_PAGE_HTML, encoding="utf-8")
    server, url = _serve(tmp_path, "no_date_filter.html")

    browser = browser_tools.build_browser(_settings(tmp_path))
    try:
        await browser.start()
        page = await browser.new_page()
        outcome = await browser_tools._task1_on_page(
            page, url, "software engineer", _settings(tmp_path), lambda _m: None
        )
        observed = json.loads(await page.evaluate(_READ_FALLBACK_JS))
    finally:
        await browser.kill()
        server.shutdown()

    assert outcome.results_found is True
    assert outcome.date_posted_filter_selected is True
    assert "URL fallback" in outcome.notes
    assert "f_TPR=r86400" in observed["url"]
    # The fallback reloaded the page, resetting the pill; the run re-selected it
    # through the URL (f_AL=true) so the date range was preserved.
    assert outcome.easy_apply_filter_selected is True
    assert observed["easy_apply_clicks"] == 0
    assert "f_AL=true" in observed["url"]
