"""Opt-in live-browser test for Task 1's "Try AI job search" handling.

It needs no LinkedIn account, no login, and no network: it serves a small
LinkedIn-shaped jobs page from a local HTTP server and drives the **real** Task 1
code path (:func:`_task1_on_page`) in a real Chromium window built by
:func:`build_browser`. This exercises what unit tests cannot: the runtime
``_AI_CANDIDATES_QUERY`` scan, CDP element resolution by the marked attribute,
the click, and the single repeat search.

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

import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from src.configuration import SessionSettings, Settings

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
# - a persistent "Try AI job search" button;
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
<!--DATE_FILTER-->
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
  document.getElementById('ai-search').addEventListener('click', function () {
    window.__aiClicks += 1;
  });
  document.getElementById('easy-apply-filter').addEventListener('click', function () {
    this.setAttribute('aria-pressed', 'true');
  });
  //DATE_FILTER_JS
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


# Task 13: a LinkedIn-shaped "Date posted" filter. The popover uses native radio
# inputs and a **Show results** button; applying it updates the URL in place
# (history.replaceState) so the rest of the fixture's counters survive. The
# agent discovers and clicks these controls at runtime.
_DATE_FILTER_HTML = """
<div id="date-posted-wrap">
  <button id="date-posted-filter" type="button" role="radio" aria-checked="false"
          aria-label="Date posted filter.">Date posted</button>
  <div id="date-posted-popover" style="display:none">
    <label for="tp-month">Past month</label>
    <input type="radio" id="tp-month" name="timePostedRange" value="r2592000">
    <label for="tp-week">Past week</label>
    <input type="radio" id="tp-week" name="timePostedRange" value="r604800">
    <label for="tp-24h">Past 24 hours</label>
    <input type="radio" id="tp-24h" name="timePostedRange" value="r86400">
    <button id="date-posted-show" type="button">Show results</button>
  </div>
</div>
"""

_DATE_FILTER_SCRIPT = """
  // Task 13: event delegation survives the AI page's body replacement.
  document.addEventListener('click', function (event) {
    var target = event.target;
    if (!target || !target.closest) { return; }
    if (target.closest('#date-posted-filter')) {
      var pop = document.getElementById('date-posted-popover');
      if (pop) { pop.style.display = pop.style.display === 'none' ? 'block' : 'none'; }
    } else if (target.closest('#date-posted-show')) {
      var checked = document.querySelector('input[name="timePostedRange"]:checked');
      if (checked) {
        var next = new URL(window.location.href);
        next.searchParams.set('f_TPR', checked.value);
        window.history.replaceState({}, '', next.toString());
        document.getElementById('date-posted-filter').setAttribute('aria-checked', 'true');
      }
      var pop = document.getElementById('date-posted-popover');
      if (pop) { pop.style.display = 'none'; }
    }
  });
"""


def _render(html: str) -> str:
    """Inject the shared Task 13 Date posted fixture into a page template."""
    return html.replace("<!--DATE_FILTER-->", _DATE_FILTER_HTML).replace(
        "//DATE_FILTER_JS", _DATE_FILTER_SCRIPT
    )



