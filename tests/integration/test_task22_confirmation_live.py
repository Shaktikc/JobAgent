"""Submission detection with stale page status and LinkedIn's verified title badge."""

import asyncio
import gc
import os

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task4Outcome
from src.tools.browser import build_browser
from src.tools.linkedin_auto_submit import _submit_on_page
from src.tools.linkedin_submission import read_submission_state

pytest.importorskip("browser_use")
pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_SUBMISSION_LIVE"), reason="set AUTOJOB_SUBMISSION_LIVE=1",
)

BODY = """<!doctype html><html><body>
<aside><span>Application submitted</span></aside>
<ul><li class="jobs-search-results__list-item">
<div>Engineer</div><div>Other company</div><div>Applied · Easy Apply</div></li>
<li class="jobs-search-results__list-item">
<div>Engineer</div><div>Example</div><div id="card-status">Viewed · Easy Apply</div></li></ul>
<dialog open id="application"><h2>Apply to Example</h2><h3>Review your application</h3>
<button id="submit" type="button">Submit application</button></dialog>
<script>
document.getElementById('submit').onclick=()=>{
  document.getElementById('application').close();
  document.getElementById('card-status').textContent='Applied · Easy Apply';
};
</script></body></html>"""


@pytest.mark.parametrize("semantic", [False, True])
@pytest.mark.parametrize("selected", [False, True])
async def test_verified_title_card_confirms_despite_an_unrelated_existing_status(
    tmp_path, semantic, selected,
):
    settings = Settings(data_dir=tmp_path / "data", session=SessionSettings(
        headless=True, auto_submit_timeout_seconds=0.3, keep_open_poll_seconds=0.05,
    ))
    browser = build_browser(settings)
    await browser.start()
    try:
        file = tmp_path / "verified.html"
        body = BODY
        if selected:
            body = body.replace(
                '<div>Engineer</div>',
                '<div>Selected, Engineer (Verified job)</div><div>Engineer</div>',
            )
        if semantic:
            body = body.replace(
                '<li class="jobs-search-results__list-item">', '<div role="button">',
            )
            body = body.replace('</li>', '</div>')
        file.write_text(body, encoding="utf-8")
        page = await browser.new_page()
        await page.goto(file.as_uri())
        title = "Engineer (Verified job)"
        initial = await read_submission_state(page, title, "Example")
        assert initial["status_submitted"] and not initial["card_applied"]
        outcome = Task4Outcome(form_open=True, reached_terminal_step=True, resume_attached=True)
        result = await _submit_on_page(page, outcome, settings, print, title, "Example")
        assert result.status == "submitted", result
    finally:
        await browser.kill()
        gc.collect()
        await asyncio.sleep(0)
