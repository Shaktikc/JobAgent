"""Resume controls below a scrolling modal must receive the actual click."""

import asyncio
import gc
import json
import os

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task4Outcome
from src.tools.browser import build_browser
from src.tools.linkedin_easy_apply_fill.resume_attachment import _attach_resume
from src.tools.linkedin_status_overlay import ensure_interaction_lock, release_interaction_lock

pytest.importorskip("browser_use")
pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_SUBMISSION_LIVE"), reason="set AUTOJOB_SUBMISSION_LIVE=1",
)


@pytest.mark.parametrize("control", ["upload", "listed"])
async def test_resume_control_below_viewport_is_clicked(tmp_path, control):
    settings = Settings(data_dir=tmp_path / "data", session=SessionSettings(
        headless=True, post_click_wait_seconds=0,
    ))
    resume = tmp_path / "chosen.pdf"
    resume.write_bytes(b"%PDF-1.4\n%%EOF")
    target = (
        '<button id="target" onclick="window.clicks++;'
        'this.insertAdjacentHTML(\'afterend\',\'<input type=file hidden>\')">'
        'Upload resume</button>' if control == "upload" else
        '<label id="target"><input type="radio" name="resume" '
        'onchange="window.clicks++">chosen.pdf</label>'
    )
    fixture = tmp_path / "resume.html"
    fixture.write_text(
        '<dialog open style="height:450px;width:500px;overflow:auto">'
        '<h2>Apply to Example</h2><div style="height:1600px">Saved resumes</div>'
        + target + '<button>Next</button></dialog><script>window.clicks=0</script>',
        encoding="utf-8",
    )
    browser = build_browser(settings)
    await browser.start()
    page = None
    try:
        page = await browser.new_page()
        await page.goto(fixture.as_uri())
        await ensure_interaction_lock(page)
        outcome = Task4Outcome()
        await _attach_resume(page, browser, str(resume), settings, outcome, print)
        observed = json.loads(await page.evaluate("""() => JSON.stringify({
          clicks:window.clicks,
          files:Array.from(document.querySelectorAll('input[type=file]'))
            .flatMap(el=>Array.from(el.files).map(f=>f.name)),
          checked:!!document.querySelector('input[type=radio]:checked')
        })"""))
        assert observed["clicks"] == 1, (outcome.model_dump(), observed)
        assert outcome.resume_attached
        if control == "upload":
            assert observed["files"] == ["chosen.pdf"]
        else:
            assert observed["checked"]
    finally:
        if page is not None:
            await release_interaction_lock(page)
        await browser.kill()
        gc.collect()
        await asyncio.sleep(0)
