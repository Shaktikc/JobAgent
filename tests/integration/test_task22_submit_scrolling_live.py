"""Submit must work when the terminal button initially sits below the viewport."""

import asyncio
import gc
import json
import os
from pathlib import Path

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task4Outcome
from src.tools.browser import build_browser
from src.tools.linkedin_auto_submit import _submit_on_page

pytest.importorskip("browser_use")
pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_SUBMISSION_LIVE"), reason="set AUTOJOB_SUBMISSION_LIVE=1",
)

BODY = """<!doctype html><html><body>
<dialog open id="application" style="height:450px;width:500px;overflow:auto">
<h2>Apply to Example</h2><h3>Review your application</h3>
<div style="height:1600px">Long application review</div>
<button id="submit" type="button">Submit application</button></dialog>
<dialog id="confirmation"><h2>Application submitted</h2><button>Done</button></dialog>
<script>
window.submitClicks=0;
document.getElementById('submit').onclick=()=>{
  submitClicks++; document.getElementById('application').close();
  document.getElementById('confirmation').showModal();
};
document.querySelector('#confirmation button').onclick=()=>
  document.getElementById('confirmation').close();
</script></body></html>"""

SNAPSHOT = """() => JSON.stringify({
  buttonTop:document.getElementById('submit').getBoundingClientRect().top,
  viewport:window.innerHeight,clicks:submitClicks,
  formOpen:document.getElementById('application').open
})"""


async def test_submit_scrolls_before_calculating_click_coordinates(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", session=SessionSettings(
        headless=True, auto_submit_timeout_seconds=0.3, keep_open_poll_seconds=0.05,
    ))
    browser = build_browser(settings)
    await browser.start()
    try:
        file = tmp_path / "offscreen.html"
        file.write_text(BODY, encoding="utf-8")
        page = await browser.new_page()
        await page.goto(file.as_uri())
        before = json.loads(await page.evaluate(SNAPSHOT))
        assert before["buttonTop"] > before["viewport"]
        outcome = Task4Outcome(form_open=True, reached_terminal_step=True, resume_attached=True)
        result = await _submit_on_page(page, outcome, settings, print)
        after = json.loads(await page.evaluate(SNAPSHOT))
        folder = Path("data/debug/task22")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "scroll-click.json").write_text(
            json.dumps({"before": before, "after": after, "result": result.status}, indent=2),
            encoding="utf-8",
        )
        assert result.status == "submitted", (result, before, after)
        assert after["clicks"] == 1
    finally:
        await browser.kill()
        gc.collect()
        await asyncio.sleep(0)
