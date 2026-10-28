"""Opt-in live-browser test for Task 17's two-way range fallback.

The fixtures serve LinkedIn-shaped results pages over HTTP. The first test's
Past 24 hours list contains only **Applied** cards, so the scan must exhaust it,
click **Date posted → Past week → Show results**, reset to page 1, and then
select the older unapplied Easy Apply job. The second test starts on Past week
and falls back to Past 24 hours. Neither test clicks **Submit application**.

Enable it (the ``browser`` extra must be installed)::

    $env:AUTOJOB_TASK17_LIVE="1"
    uv run pytest tests/integration/test_task17_past_week_live.py -s

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
        not os.environ.get("AUTOJOB_TASK17_LIVE"),
        reason="set AUTOJOB_TASK17_LIVE=1 to run the live Task 17 browser test",
    ),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

_PAGE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Jobs</title></head>
<body>
<button id="searchFilter_applyWithLinkedin" type="button" role="radio"
        aria-checked="true" aria-label="Easy Apply filter."
        class="artdeco-pill">Easy Apply</button>
<button id="searchFilter_timePostedRange" type="button" role="radio"
        aria-checked="true" aria-label="Date posted filter.">Date posted</button>
<div id="date-posted-popover" style="display:none">
  <label for="tp-month">Past month</label>
  <input type="radio" id="tp-month" name="timePostedRange" value="r2592000">
  <label for="tp-week">Past week</label>
  <input type="radio" id="tp-week" name="timePostedRange" value="r604800">
  <label for="tp-24h">Past 24 hours</label>
  <input type="radio" id="tp-24h" name="timePostedRange" value="r86400" checked>
  <button id="date-posted-show" type="button">Show results</button>
</div>
<ul class="jobs-search__results-list" id="results">
  <li class="jobs-search-results__list-item">
    <div class="base-search-card__title">24h Applied One</div>
    <div class="base-search-card__subtitle">Acme</div>
    <div class="job-search-card__snippet">Applied · 5 months ago</div>
    <div class="job-search-card__snippet">Easy Apply</div>
  </li>
  <li class="jobs-search-results__list-item">
    <div class="base-search-card__title">24h Applied Two</div>
    <div class="base-search-card__subtitle">Acme</div>
    <div class="job-search-card__snippet">Applied · 2 weeks ago</div>
    <div class="job-search-card__snippet">Easy Apply</div>
  </li>
</ul>
<div class="jobs-search__job-details--container" style="display:none">
  <h1 class="job-details-jobs-unified-top-card__job-title"></h1>
  <button class="jobs-apply-button" type="button"
          aria-label="Easy Apply to the selected job at Acme">Easy Apply</button>
</div>
<div class="jobs-easy-apply-modal artdeco-modal" role="dialog" style="display:none">
  <div class="artdeco-modal__content">Easy Apply. Review your application.</div>
</div>
<script>
  var results = document.getElementById('results');
  var details = document.querySelector('.jobs-search__job-details--container');
  var title = document.querySelector('.job-details-jobs-unified-top-card__job-title');
  var apply = details.querySelector('.jobs-apply-button');
  var modal = document.querySelector('.jobs-easy-apply-modal');
  window.__submitClicks = 0;
  window.__weekSelected = false;
  function wireCards() {
    document.querySelectorAll('li.jobs-search-results__list-item').forEach(function (li) {
      li.addEventListener('click', function () {
        details.style.display = 'block';
        var name = (li.innerText || '').split('\\n')[0].trim() || 'the selected job';
        title.textContent = name;
        apply.setAttribute('aria-label', 'Easy Apply to ' + name + ' at Acme');
      });
    });
  }
  wireCards();
  document.getElementById('searchFilter_timePostedRange').addEventListener('click', function () {
    var pop = document.getElementById('date-posted-popover');
    pop.style.display = pop.style.display === 'none' ? 'block' : 'none';
  });
  document.getElementById('date-posted-show').addEventListener('click', function () {
    var checked = document.querySelector('input[name="timePostedRange"]:checked');
    if (checked && checked.value === 'r604800') {
      window.__weekSelected = true;
      results.innerHTML =
        '<li class="jobs-search-results__list-item">' +
        '<div class="base-search-card__title">Older Week Job</div>' +
        '<div class="base-search-card__subtitle">Acme</div>' +
        '<div class="job-search-card__snippet">Viewed 3 days ago</div>' +
        '<div class="job-search-card__snippet">Easy Apply</div></li>';
      wireCards();
    }
    if (checked) {
      var next = new URL(window.location.href);
      next.searchParams.set('f_TPR', checked.value);
      window.history.replaceState({}, '', next.toString());
    }
    document.getElementById('date-posted-popover').style.display = 'none';
  });
  apply.addEventListener('click', function () {
    modal.style.display = 'block';
  });
  document.querySelector('.artdeco-modal__content').addEventListener('click', function () {
    window.__submitClicks += 1;
  });
</script>
</body></html>
"""


_WEEK_FIRST_PAGE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Jobs</title></head>
<body>
<button id="searchFilter_applyWithLinkedin" type="button" role="radio"
        aria-checked="true" aria-label="Easy Apply filter."
        class="artdeco-pill">Easy Apply</button>
<button id="searchFilter_timePostedRange" type="button" role="radio"
        aria-checked="true" aria-label="Date posted filter.">Date posted</button>
<div id="date-posted-popover" style="display:none">
  <label for="tp-month">Past month</label>
  <input type="radio" id="tp-month" name="timePostedRange" value="r2592000">
  <label for="tp-week">Past week</label>
  <input type="radio" id="tp-week" name="timePostedRange" value="r604800" checked>
  <label for="tp-24h">Past 24 hours</label>
  <input type="radio" id="tp-24h" name="timePostedRange" value="r86400">
  <button id="date-posted-show" type="button">Show results</button>
</div>
<ul class="jobs-search__results-list" id="results">
  <li class="jobs-search-results__list-item">
    <div class="base-search-card__title">Week Applied One</div>
    <div class="base-search-card__subtitle">Acme</div>
    <div class="job-search-card__snippet">Applied · 3 days ago</div>
    <div class="job-search-card__snippet">Easy Apply</div>
  </li>
</ul>
<div class="jobs-search__job-details--container" style="display:none">
  <h1 class="job-details-jobs-unified-top-card__job-title"></h1>
  <button class="jobs-apply-button" type="button"
          aria-label="Easy Apply to the selected job at Acme">Easy Apply</button>
</div>
<div class="jobs-easy-apply-modal artdeco-modal" role="dialog" style="display:none">
  <div class="artdeco-modal__content">Easy Apply. Review your application.</div>
</div>
<script>
  var results = document.getElementById('results');
  var details = document.querySelector('.jobs-search__job-details--container');
  var title = document.querySelector('.job-details-jobs-unified-top-card__job-title');
  var apply = details.querySelector('.jobs-apply-button');
  var modal = document.querySelector('.jobs-easy-apply-modal');
  window.__submitClicks = 0;
  window.__twentyFourSelected = false;
  function wireCards() {
    document.querySelectorAll('li.jobs-search-results__list-item').forEach(function (li) {
      li.addEventListener('click', function () {
        details.style.display = 'block';
        var name = (li.innerText || '').split('\\n')[0].trim() || 'the selected job';
        title.textContent = name;
        apply.setAttribute('aria-label', 'Easy Apply to ' + name + ' at Acme');
      });
    });
  }
  wireCards();
  document.getElementById('searchFilter_timePostedRange').addEventListener('click', function () {
    var pop = document.getElementById('date-posted-popover');
    pop.style.display = pop.style.display === 'none' ? 'block' : 'none';
  });
  document.getElementById('date-posted-show').addEventListener('click', function () {
    var checked = document.querySelector('input[name="timePostedRange"]:checked');
    if (checked && checked.value === 'r86400') {
      window.__twentyFourSelected = true;
      results.innerHTML =
        '<li class="jobs-search-results__list-item">' +
        '<div class="base-search-card__title">24h Only Job</div>' +
        '<div class="base-search-card__subtitle">Acme</div>' +
        '<div class="job-search-card__snippet">Viewed 2 days ago</div>' +
        '<div class="job-search-card__snippet">Easy Apply</div></li>';
      wireCards();
    }
    if (checked) {
      var next = new URL(window.location.href);
      next.searchParams.set('f_TPR', checked.value);
      window.history.replaceState({}, '', next.toString());
    }
    document.getElementById('date-posted-popover').style.display = 'none';
  });
  apply.addEventListener('click', function () {
    modal.style.display = 'block';
  });
</script>
</body></html>
"""


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
            easy_apply_timeout_seconds=1.0,
            ask_human=False,
        ),
        data_dir=tmp_path / "data",
    )


async def _read_state(page) -> dict:
    return json.loads(
        await page.evaluate(
            "() => JSON.stringify({"
            "  week_selected: window.__weekSelected,"
            "  submit_clicks: window.__submitClicks,"
            "  url: window.location.href,"
            "  card: (() => {"
            "    const first = document.querySelector('li.jobs-search-results__list-item');"
            "    return first ? first.innerText : '';"
            "  })()"
            "})"
        )
    )


async def _read_week_first_state(page) -> dict:
    return json.loads(
        await page.evaluate(
            "() => JSON.stringify({"
            "  twenty_four_selected: window.__twentyFourSelected,"
            "  submit_clicks: window.__submitClicks,"
            "  url: window.location.href,"
            "  card: (() => {"
            "    const first = document.querySelector('li.jobs-search-results__list-item');"
            "    return first ? first.innerText : '';"
            "  })()"
            "})"
        )
    )


async def test_past_24_hours_exhaustion_switches_to_past_week(tmp_path: Path) -> None:
    page_file = tmp_path / "task17.html"
    page_file.write_text(_PAGE_HTML, encoding="utf-8")
    server, url = _serve(tmp_path, "task17.html")

    browser = browser_tools.build_browser(_settings(tmp_path))
    try:
        await browser.start()
        page = await browser.new_page()
        await page.goto(f"{url}?keywords=software+engineer&f_AL=true&f_TPR=r86400")
        await browser_tools._wait_for_load(page, 10)
        outcome = await browser_tools._task2_on_page(
            page, _settings(tmp_path), lambda _m: None, open_form=False
        )
        observed = await _read_state(page)
    finally:
        await browser.kill()
        server.shutdown()

    assert outcome.date_range_fallback_used is True
    assert outcome.date_range_used == "past_week"
    assert outcome.pages_visited_past_week == 1
    assert outcome.job_selected is True
    assert outcome.job_title == "Older Week Job"
    assert outcome.easy_apply_clicked is False
    assert outcome.application_form_opened is False

    assert observed["week_selected"] is True
    assert "f_TPR=r604800" in observed["url"]
    assert "f_AL=true" in observed["url"]
    assert "Older Week Job" in observed["card"]
    assert observed["submit_clicks"] == 0


async def test_past_week_exhaustion_switches_to_past_24_hours(tmp_path: Path) -> None:
    page_file = tmp_path / "task17_week_first.html"
    page_file.write_text(_WEEK_FIRST_PAGE_HTML, encoding="utf-8")
    server, url = _serve(tmp_path, "task17_week_first.html")

    browser = browser_tools.build_browser(_settings(tmp_path))
    try:
        await browser.start()
        page = await browser.new_page()
        await page.goto(f"{url}?keywords=software+engineer&f_AL=true&f_TPR=r604800")
        await browser_tools._wait_for_load(page, 10)
        outcome = await browser_tools._task2_on_page(
            page,
            _settings(tmp_path),
            lambda _m: None,
            open_form=False,
            date_range="past_week",
            preferred_range="past_week",
        )
        observed = await _read_week_first_state(page)
    finally:
        await browser.kill()
        server.shutdown()

    assert outcome.date_range_preferred == "past_week"
    assert outcome.date_range_fallback_used is True
    assert outcome.date_range_used == "past_24_hours"
    assert outcome.pages_visited == 2
    assert outcome.pages_visited_past_week == 1
    assert outcome.job_selected is True
    assert outcome.job_title == "24h Only Job"
    assert outcome.easy_apply_clicked is False
    assert outcome.application_form_opened is False

    assert observed["twenty_four_selected"] is True
    assert "f_TPR=r86400" in observed["url"]
    assert "f_AL=true" in observed["url"]
    assert "24h Only Job" in observed["card"]
    assert observed["submit_clicks"] == 0
