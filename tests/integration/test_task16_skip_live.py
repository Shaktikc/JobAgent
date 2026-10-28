"""Opt-in live-browser tests for Task 16's Easy Apply open/close controls.

The match-first flow selects a job and leaves Easy Apply closed, then
:func:`open_easy_apply_form` clicks it only after the resume match. A form left
open by a self-healed retry or a legacy fallback is closed with
:func:`close_easy_apply_form`. Neither path may click **Submit application**.

These tests serve LinkedIn-shaped fixtures in a real Chromium window. They need
no LinkedIn account and no network.

Enable it (the ``browser`` extra must be installed)::

    $env:AUTOJOB_RESUME_GATE_LIVE="1"
    uv run pytest tests/integration/test_task16_skip_live.py -s
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task2Outcome
from src.tools import browser as browser_tools
from src.tools.linkedin_easy_apply_open import open_easy_apply_form
from src.tools.linkedin_resume_gate import close_easy_apply_form

pytest.importorskip("browser_use")

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("AUTOJOB_RESUME_GATE_LIVE"),
        reason="set AUTOJOB_RESUME_GATE_LIVE=1 to run the live Task 16 browser test",
    ),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

_MODAL_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Jobs</title></head>
<body>
<div class="artdeco-modal artdeco-modal--layer-default jobs-easy-apply-modal"
     role="dialog" id="apply-modal">
  <button class="artdeco-modal__dismiss" aria-label="Dismiss" id="x-btn">X</button>
  <div class="artdeco-modal__content">
    <h2>Apply to Acme</h2>
    <label>Phone number <input type="tel" /></label>
  </div>
  <footer class="artdeco-modal__actionbar">
    <button id="next-btn" type="button">Next</button>
    <button id="submit-btn" type="button">Submit application</button>
  </footer>
  <div id="discard-confirm" style="display:none">
    <p>Discard application?</p>
    <button id="discard-btn" type="button">Discard</button>
    <button id="cancel-btn" type="button">Cancel</button>
  </div>
</div>

<script>
  window.__xClicked = false;
  window.__discardClicked = false;
  window.__cancelClicked = false;
  window.__submitClicked = false;
  window.__nextClicked = false;
  var modal = document.getElementById('apply-modal');
  var confirm = document.getElementById('discard-confirm');
  function hide() { modal.style.display = 'none'; }
  document.getElementById('x-btn').addEventListener('click', function () {
    window.__xClicked = true;
    confirm.style.display = 'block';
  });
  document.getElementById('discard-btn').addEventListener('click', function () {
    window.__discardClicked = true; hide();
  });
  document.getElementById('cancel-btn').addEventListener('click', function () {
    window.__cancelClicked = true;
  });
  document.getElementById('next-btn').addEventListener('click', function () {
    window.__nextClicked = true;
  });
  document.getElementById('submit-btn').addEventListener('click', function () {
    window.__submitClicked = true;
  });
</script>
</body></html>
"""

_SELECT_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Jobs</title></head>
<body>
<button class="jobs-apply-button" id="apply-btn" type="button"
        aria-label="Easy Apply to Acme">Easy Apply</button>
<div class="artdeco-modal jobs-easy-apply-modal" role="dialog" id="apply-modal"
     style="display:none">
  <div class="artdeco-modal__content">
    <h2>Apply to Acme</h2>
    <label>Phone number <input type="tel" /></label>
  </div>
  <footer class="artdeco-modal__actionbar">
    <button id="next-btn" type="button">Next</button>
    <button id="submit-btn" type="button">Submit application</button>
  </footer>
</div>
<script>
  window.__applyClicked = false;
  window.__submitClicked = false;
  var modal = document.getElementById('apply-modal');
  document.getElementById('apply-btn').addEventListener('click', function () {
    window.__applyClicked = true;
    modal.style.display = 'block';
  });
  document.getElementById('submit-btn').addEventListener('click', function () {
    window.__submitClicked = true;
  });
</script>
</body></html>
"""

_MODAL_NO_CONFIRM_HTML = _MODAL_HTML.replace(
    "confirm.style.display = 'block';",
    "hide();",
).replace(
    """  window.__discardClicked = false;
  window.__cancelClicked = false;
""",
    "",
)


def _settings(tmp_path: Path) -> Settings:
    headless = os.environ.get("AUTOJOB_SESSION_HEADLESS", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    return Settings(
        session=SessionSettings(headless=headless, post_click_wait_seconds=0.0),
        data_dir=tmp_path / "data",
    )


async def _open_fixture(tmp_path: Path, settings: Settings, html: str):
    page_file = tmp_path / "easy_apply.html"
    page_file.write_text(html, encoding="utf-8")
    browser = browser_tools.build_browser(settings)
    await browser.start()
    page = await browser.new_page()
    await page.goto(page_file.as_uri())
    await browser_tools._wait_for_load(page, 10)
    return browser, page


async def _flags(page) -> dict:
    raw = await page.evaluate(
        "() => JSON.stringify({"
        " x: window.__xClicked,"
        " submit: window.__submitClicked,"
        " next: window.__nextClicked,"
        " modal_visible: (() => { const m = document.getElementById('apply-modal');"
        "   return m ? m.getClientRects().length > 0 : false; })()"
        "})"
    )
    return json.loads(raw)


async def test_easy_apply_is_clicked_only_when_the_match_flow_opens_it(
    tmp_path: Path,
) -> None:
    """Task 16: selecting the job leaves Easy Apply closed until the matcher calls."""
    settings = _settings(tmp_path)
    browser, page = await _open_fixture(tmp_path, settings, _SELECT_HTML)
    try:
        before = json.loads(
            await page.evaluate(
                "() => JSON.stringify({"
                " clicked: window.__applyClicked,"
                " visible: (() => { const m = document.getElementById('apply-modal');"
                "   return m ? m.getClientRects().length > 0 : false; })()"
                "})"
            )
        )
        opened, outcome = await open_easy_apply_form(
            page,
            settings,
            None,
            Task2Outcome(
                job_title="Acme", job_selected=True, easy_apply_button_found=True
            ),
        )
        after = json.loads(
            await page.evaluate(
                "() => JSON.stringify({"
                " clicked: window.__applyClicked,"
                " submit: window.__submitClicked,"
                " visible: (() => { const m = document.getElementById('apply-modal');"
                "   return m ? m.getClientRects().length > 0 : false; })()"
                "})"
            )
        )
    finally:
        await browser.kill()

    assert before["clicked"] is False and before["visible"] is False
    assert opened is True
    assert after["clicked"] is True
    assert after["visible"] is True
    assert after["submit"] is False, "Submit application was clicked!"
    assert outcome.easy_apply_clicked is True
    assert outcome.application_form_opened is True


async def test_dismiss_closes_the_form_and_never_submits(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    browser, page = await _open_fixture(tmp_path, settings, _MODAL_NO_CONFIRM_HTML)
    try:
        closed = await close_easy_apply_form(page, settings)
        flags = await _flags(page)
    finally:
        await browser.kill()

    assert closed is True
    assert flags["modal_visible"] is False
    assert flags["x"] is True
    assert flags["submit"] is False, "Submit application was clicked!"
    assert flags["next"] is False, "the form was advanced instead of closed"


async def test_discard_confirmation_closes_the_draft_without_submitting(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    browser, page = await _open_fixture(tmp_path, settings, _MODAL_HTML)
    try:
        closed = await close_easy_apply_form(page, settings)
        flags = await _flags(page)
        extra = json.loads(
            await page.evaluate(
                "() => JSON.stringify({"
                " discard: window.__discardClicked,"
                " cancel: window.__cancelClicked"
                "})"
            )
        )
    finally:
        await browser.kill()

    assert closed is True
    assert flags["modal_visible"] is False
    assert extra["discard"] is True
    assert extra["cancel"] is False
    assert flags["submit"] is False, "Submit application was clicked!"
    assert flags["next"] is False
