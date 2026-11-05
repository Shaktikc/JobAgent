"""Actual Chromium inputs, server-style errors, rerenders and one retry."""

import json
import os

import pytest

from src.configuration import SessionSettings, Settings
from src.tools.browser import build_browser
from src.tools.linkedin_easy_apply_fill.form_walk import _task4_on_page
from src.tools.llm_answers import QuestionDecision

pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_FILL_LIVE"), reason="set AUTOJOB_FILL_LIVE=1"
)


@pytest.mark.parametrize(
    ("metadata", "answer", "accepted", "persistent"),
    [
        ('inputmode="numeric"', "2 years", "2", False),
        ('inputmode="numeric"', "2 years", "2", True),
        ('type="text"', "2", "2 years", False),
        ('type="text"', "2 years", "2", False),
        ('type="number"', "2 years", "2", False),
    ],
)
async def test_walk_repairs_rejected_type_and_stops_before_submit(
    tmp_path,
    metadata,
    answer,
    accepted,
    persistent,
):
    settings = Settings(
        data_dir=tmp_path / "data",
        session=SessionSettings(
            headless=True,
            ask_human=False,
            easy_apply_timeout_seconds=0.2,
            post_click_wait_seconds=0,
        ),
    )
    fixture = tmp_path / "conversion.html"
    fixture.write_text(
        """<dialog open><h2>Apply to Example</h2>
      <section id="questions"><h3>Screening</h3><div>
      <label for="experience">How many years of experience?*</label>
      <input id="experience" METADATA aria-describedby="error">
      <p id="error" hidden>Invalid input</p></div>
      <label for="optional">Optional</label><input id="optional" value="Keep me">
      <button onclick="advance()">Next</button></section>
      <section id="review" hidden><h3>Review application</h3>
      <button onclick="window.submitted=true">Submit application</button></section></dialog>
      <script>window.clicks=0;window.submitted=false;
      function advance(){window.clicks++;const input=document.getElementById('experience');
        if(PERSISTENT || input.value !== ACCEPTED){
          const copy=input.cloneNode(true);copy.setAttribute('aria-invalid','true');
          input.replaceWith(copy);document.getElementById('error').hidden=false;
        }else{document.getElementById('questions').hidden=true;
          document.getElementById('review').hidden=false;}}
      </script>""".replace("METADATA", metadata)
        .replace("PERSISTENT", str(persistent).lower())
        .replace("ACCEPTED", json.dumps(accepted)),
        encoding="utf-8",
    )
    browser = build_browser(settings)
    await browser.start()
    try:
        page = await browser.new_page(fixture.as_uri())

        async def choose(question, kind, options):
            return QuestionDecision(question=question, answer=answer, source_keys=["approved"])

        outcome = await _task4_on_page(
            page,
            browser,
            None,
            {},
            settings,
            lambda _: None,
            chooser=choose,
        )
        state = json.loads(
            await page.evaluate("""() => JSON.stringify({
          clicks:window.clicks,submitted:window.submitted,
          answer:document.getElementById('experience').value,
          optional:document.getElementById('optional').value})""")
        )
        assert state == {"clicks": 2, "submitted": False, "answer": accepted, "optional": "Keep me"}
        assert outcome.reached_terminal_step is not persistent
        assert bool(outcome.validation.issues) is persistent
        assert outcome.validation.type_conversion_attempts[0].outcome == (
            "rejected" if persistent else "accepted"
        )
        assert not (settings.data_dir / "invalid_input_skips.json").exists()
    finally:
        await browser.kill()
