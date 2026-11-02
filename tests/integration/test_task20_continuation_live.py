"""A real browser must save, discard, then choose a different posting ID."""

import json
import os

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task2Outcome
from src.tools.browser import build_browser
from src.tools.linkedin_easy_apply_fill.form_walk import _task4_on_page
from src.tools.linkedin_job_selection import _scan_page

pytest.importorskip("browser_use")
pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_FILL_LIVE"), reason="set AUTOJOB_FILL_LIVE=1"
)


async def test_json_discard_and_same_title_posting_exclusion(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        session=SessionSettings(
            headless=True,
            ask_human=False,
            post_click_wait_seconds=0,
            easy_apply_timeout_seconds=0.25,
        ),
    )
    fixture = tmp_path / "continuation.html"
    fixture.write_text(
        """<link rel="canonical" href="https://www.linkedin.com/jobs/view/123/">
      <ul><li class="jobs-search-results__list-item" componentkey="job-card-component-ref-123"
        onclick="window.selected='123'">Engineer</li>
      <li class="jobs-search-results__list-item" componentkey="job-card-component-ref-456"
        onclick="window.selected='456'">Engineer</li></ul>
      <main class="jobs-details"><h1>Engineer</h1>
        <button class="jobs-apply-button" aria-label="Easy Apply to Example">Easy Apply</button>
      </main><dialog open id="apply"><h2>Apply to Example</h2>
        <button aria-label="Dismiss"
          onclick="document.getElementById('confirm').hidden=false">X</button>
        <div><label for="salary">Salary*</label><input id="salary" value="1200" inputmode="numeric"
          aria-describedby="error"><p id="error" hidden>Invalid input</p></div>
        <button onclick="window.next++;document.getElementById('error').hidden=false;
          document.getElementById('salary').setAttribute('aria-invalid','true')">Next</button>
        <button onclick="window.submitted=true">Submit application</button>
        <div id="confirm" hidden><p>Discard application?</p>
          <button onclick="window.discarded=true;
            document.getElementById('apply').style.display='none'">
            Discard</button></div>
      </dialog><script>window.next=0;window.selected='';window.discarded=false;
        window.submitted=false;</script>""",
        encoding="utf-8",
    )
    browser = build_browser(settings)
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(fixture.as_uri())
        outcome = await _task4_on_page(page, browser, None, {}, settings, lambda _: None)
        assert outcome.validation.skipped
        assert outcome.validation.job_id == "123"
        records = json.loads((settings.data_dir / "invalid_input_skips.json").read_text())
        assert records[0]["job_url"] == "https://www.linkedin.com/jobs/view/123/"
        assert records[0]["retry_count"] == 1
        selected = Task2Outcome()
        scan = await _scan_page(
            page,
            settings,
            lambda _: None,
            selected,
            {"job:123"},
            set(),
            open_form=False,
        )
        assert scan.selected
        state = json.loads(
            await page.evaluate("""() => JSON.stringify({
          selected:window.selected,discarded:window.discarded,submitted:window.submitted,
          next:window.next})""")
        )
        assert state == {"selected": "456", "discarded": True, "submitted": False, "next": 2}
    finally:
        await browser.kill()
