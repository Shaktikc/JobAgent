"""Opt-in live-browser test for Task 8's post-apply dialog dismissal.

It needs no LinkedIn account, no login, and no network: it serves a self-contained
fixture reproducing the dialog the user hit after submitting — **"Your application
was sent to <company>!"** with a **"Turn your resume into a profile that
recruiters notice"** promo and the buttons **Not now** / **Update profile** (plus
an X) — and drives the **real** Task 8 code path in a real Chromium window built
by :func:`build_browser`.

This exercises what unit tests cannot: reading the dialog's real ``innerText``,
matching the dismiss label in the live DOM, and proving the agent clicks **Not
now** (never the X or **Update profile**) and closes the dialog so the loop can
open the next job.

Enable it (the ``browser`` extra must be installed)::

    uv sync --extra browser
    uvx playwright install chromium
    $env:AUTOJOB_APPLY_LOOP_LIVE="1"
    uv run pytest tests/integration/test_apply_loop_live.py -s

Watch it with the window shown::

    $env:AUTOJOB_APPLY_LOOP_LIVE="1"
    $env:AUTOJOB_SESSION_HEADLESS="false"
    uv run pytest tests/integration/test_apply_loop_live.py -s

Skipped by default so the unit suite stays offline.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from src.configuration import SessionSettings, Settings
from src.tools import browser as browser_tools
from src.tools.browser import _first_element
from src.tools.linkedin_apply_loop import (
    await_human_submit,
    dismiss_post_apply_modals,
    read_submission_state,
)

pytest.importorskip("browser_use")

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("AUTOJOB_APPLY_LOOP_LIVE"),
        reason="set AUTOJOB_APPLY_LOOP_LIVE=1 to run the live Task 8 browser test",
    ),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

# Reproduces the post-apply dialog from the report: the confirmation heading, the
# resume-to-profile promo, and the three controls (an X, "Not now", "Update
# profile"). The dialog starts hidden; ``window.__showPostApply()`` reveals it, so
# a test can model the human submitting *during* the wait. Each control records
# that it was clicked so the test can prove only "Not now" was used.
_MODAL_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Jobs</title></head>
<body>
<ul class="jobs-search__results-list">
  <li class="jobs-search-results__list-item">
    <div class="base-search-card__title">Backend Engineer</div>
    <div class="base-search-card__subtitle">Cleared Recruitment</div>
    <div class="job-search-card__snippet">Applied 5 months ago</div>
    <div class="job-search-card__snippet">Easy Apply</div>
  </li>
  <li class="jobs-search-results__list-item">
    <div class="base-search-card__title">Data Engineer</div>
    <div class="base-search-card__subtitle">Beta</div>
    <div class="job-search-card__snippet">Viewed 2 weeks ago</div>
    <div class="job-search-card__snippet">Easy Apply</div>
  </li>
</ul>

<div class="artdeco-modal artdeco-modal--layer-default" role="dialog"
     id="post-apply" data-test-modal-container style="display:none">
  <button class="artdeco-modal__dismiss" aria-label="Dismiss" id="x-btn">X</button>
  <div class="artdeco-modal__content">
    <h2>Your application was sent to Cleared Recruitment!</h2>
    <p>You can keep track of your application in the "Applied" tab of My Jobs</p>
    <div class="promo">
      <h3>Turn your resume into a profile that recruiters notice</h3>
      <p>Easily use your resume to enhance your profile, save time and stand out
         in your job search</p>
    </div>
  </div>
  <footer class="artdeco-modal__actionbar">
    <button id="not-now" type="button">Not now</button>
    <button id="update-profile" type="button">Update profile</button>
  </footer>
</div>

<script>
  window.__notNowClicked = false;
  window.__xClicked = false;
  window.__updateClicked = false;
  var modal = document.getElementById('post-apply');
  function close() { modal.style.display = 'none'; }
  // The human's "Submit application" click reveals the post-apply dialog.
  window.__showPostApply = function () { modal.style.display = 'block'; };
  document.getElementById('not-now').addEventListener('click', function () {
    window.__notNowClicked = true; close();
  });
  document.getElementById('x-btn').addEventListener('click', function () {
    window.__xClicked = true; close();
  });
  document.getElementById('update-profile').addEventListener('click', function () {
    window.__updateClicked = true;
  });
</script>
</body></html>
"""


class _StubSession:
    """A stand-in for the live session so ``await_human_submit`` never stops it."""

    is_cdp_connected = True

    async def stop(self) -> None:
        pass

    async def kill(self) -> None:
        pass


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
            keep_open_timeout_seconds=10.0,
            keep_open_poll_seconds=0.1,
        ),
        # A throwaway profile keeps the developer's real run untouched.
        data_dir=tmp_path / "data",
    )


async def _open_fixture(tmp_path: Path, settings: Settings, *, shown: bool):
    page_file = tmp_path / "post_apply.html"
    page_file.write_text(_MODAL_HTML, encoding="utf-8")
    browser = browser_tools.build_browser(settings)
    await browser.start()
    page = await browser.new_page()
    await page.goto(page_file.as_uri())
    await browser_tools._wait_for_load(page, 10)
    if shown:
        await page.evaluate("() => window.__showPostApply()")
    return browser, page


async def _flags(page) -> dict:
    raw = await page.evaluate(
        "() => JSON.stringify({"
        " not_now: window.__notNowClicked,"
        " x: window.__xClicked,"
        " update: window.__updateClicked,"
        " modal_visible: (() => { const m = document.getElementById('post-apply');"
        "   return m ? m.getClientRects().length > 0 : false; })()"
        "})"
    )
    return json.loads(raw)


async def test_probe_marks_not_now_for_the_promo_dialog(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    browser, page = await _open_fixture(tmp_path, settings, shown=True)
    try:
        state = await read_submission_state(page, "Backend Engineer")
        assert "application was sent" in state["confirmation"].lower()
        assert state["done_marker"], "no dismiss control marked"

        marked = await _first_element(
            page, [f'[data-autojob-done="{state["done_marker"]}"]']
        )
        assert marked is not None
        label = await marked.evaluate("() => this.innerText")
        assert (label or "").strip().lower() == "not now"
    finally:
        await browser.kill()


async def test_dismiss_clicks_not_now_and_never_update_profile(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    browser, page = await _open_fixture(tmp_path, settings, shown=True)
    try:
        await dismiss_post_apply_modals(page, "Backend Engineer")
        flags = await _flags(page)
    finally:
        await browser.kill()

    assert flags["not_now"] is True
    assert flags["x"] is False, "the X was clicked instead of Not now"
    assert flags["update"] is False, "Update profile was clicked!"
    assert flags["modal_visible"] is False, "the dialog did not close"


async def test_await_human_submit_detects_and_dismisses_the_promo(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    # Start with the dialog hidden (the human has not submitted yet) and reveal it
    # mid-wait, exactly as LinkedIn does after the Submit click.
    browser, page = await _open_fixture(tmp_path, settings, shown=False)
    run_id = "live-promo"
    browser_tools._ACTIVE_RUNS[run_id] = browser_tools._Run(session=_StubSession(), page=page)

    async def human_submits() -> None:
        await asyncio.sleep(0.5)
        await page.evaluate("() => window.__showPostApply()")

    submit = asyncio.create_task(human_submits())
    try:
        result = await await_human_submit(run_id, settings, title="Backend Engineer")
        flags = await _flags(page)
    finally:
        await submit
        browser_tools._ACTIVE_RUNS.pop(run_id, None)
        await browser.kill()

    assert result == "submitted"
    assert flags["not_now"] is True
    assert flags["x"] is False
    assert flags["update"] is False
    assert flags["modal_visible"] is False
