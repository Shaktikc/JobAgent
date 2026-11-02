"""Visible feedback must not prevent required answers or discard the application."""

import json
import os

import pytest

from src.configuration import SessionSettings, Settings
from src.tools.browser import build_browser
from src.tools.linkedin_easy_apply_fill.form_walk import _task4_on_page
from src.tools.llm_answers import QuestionDecision

pytest.importorskip("browser_use")
pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_FILL_LIVE"), reason="set AUTOJOB_FILL_LIVE=1"
)

BODY = """<dialog open><h2>Apply to Example</h2>
<section id="questions"><div><p>What's your expected annual base salary?*</p>
  <div><div><input id="salary" required aria-invalid="true"></div>
    <div data-testid="text-input-helper-text"><p>Invalid input</p><p>0/20</p></div>
  </div></div>
  <label for="optional">Additional details</label><input id="optional" value="Keep this">
  <button type="button" onclick="document.getElementById('questions').hidden=true;
    document.getElementById('review').hidden=false">Next</button>
</section>
<section id="review" hidden><h3>Review your application</h3>
  <button type="button" onclick="window.submitted=true">Submit application</button>
</section></dialog><script>window.submitted=false;</script>"""


async def test_existing_field_feedback_allows_required_filling_and_normal_navigation(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", session=SessionSettings(
        headless=True, ask_human=False, post_click_wait_seconds=0,
        easy_apply_timeout_seconds=2,
    ))
    browser = build_browser(settings)
    await browser.start()
    try:
        fixture = tmp_path / "form_feedback.html"
        fixture.write_text(BODY, encoding="utf-8")
        page = await browser.new_page()
        await page.goto(fixture.as_uri())
        calls = []

        async def chooser(question, kind, options):
            calls.append(question)
            return QuestionDecision(question=question, answer="120000")

        outcome = await _task4_on_page(
            page, browser, None, {}, settings, lambda _: None, chooser=chooser,
        )
        assert outcome.filled_fields == 1
        assert outcome.steps_advanced == 1
        assert outcome.reached_terminal_step and not outcome.submitted
        assert calls == ["What's your expected annual base salary?*"]
        assert json.loads(await page.evaluate("""() => JSON.stringify([
          document.getElementById('salary').value,
          document.getElementById('optional').value, window.submitted
        ])""")) == ["120000", "Keep this", False]
        assert not list(settings.data_dir.glob("*.jsonl"))
    finally:
        await browser.kill()
