"""Real Chromium checks for correction, feedback scope, and bounded retries."""

import json
import os

import pytest

from src.configuration import SessionSettings, Settings
from src.tools.browser import build_browser
from src.tools.linkedin_easy_apply_fill.form_queries import read_form
from src.tools.linkedin_easy_apply_fill.form_walk import _task4_on_page
from src.tools.linkedin_validation.detection import read_rejections
from src.tools.llm_answers import QuestionDecision

pytest.importorskip("browser_use")
pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_FILL_LIVE"), reason="set AUTOJOB_FILL_LIVE=1"
)


async def test_detection_ignores_information_hidden_and_unrelated_text(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", session=SessionSettings(headless=True))
    browser = build_browser(settings)
    await browser.start()
    try:
        fixture = tmp_path / "validation.html"
        fixture.write_text(
            """<p>Invalid input outside the form</p>
          <dialog open><h2>Apply to Example</h2>
          <label for="email">Email*</label><input id="email" value="private@example.org"
            aria-describedby="info">
          <span id="info" class="artdeco-inline-feedback__message">Your email stays private</span>
          <div hidden><label for="hidden">Hidden*</label><input id="hidden" aria-invalid="true">
            <p>Invalid input</p></div>
          <div><label for="salary">Salary*</label><input id="salary" value="120000"
            aria-invalid="true" aria-describedby="error">
            <div id="error"><p>Invalid input: 120000</p><p>6/20</p></div></div>
          <div><label for="notice">Notice*</label><input id="notice" aria-errormessage="feedback">
            <p id="feedback">Enter a whole number</p></div>
          <button>Next</button></dialog>""",
            encoding="utf-8",
        )
        page = await browser.new_page()
        await page.goto(fixture.as_uri())
        _, _, fields, _ = await read_form(page)
        issues = await read_rejections(page, fields)
        assert len(issues) == 2
        assert issues[0]["question"] == "Salary*"
        assert "120000" not in issues[0]["message"]
        assert issues[0]["field"]["maxlength"] == 20
        assert issues[1]["question"] == "Notice*"
        assert issues[1]["message"] == "Enter a whole number"
    finally:
        await browser.kill()


@pytest.mark.parametrize("persistent", [False, True])
async def test_walker_corrects_once_then_recovers_or_reports_rejection(tmp_path, persistent):
    settings = Settings(
        data_dir=tmp_path / "data",
        session=SessionSettings(
            headless=True,
            ask_human=False,
            post_click_wait_seconds=0,
            easy_apply_timeout_seconds=0.5,
        ),
    )
    browser = build_browser(settings)
    await browser.start()
    try:
        fixture = tmp_path / "retry.html"
        fixture.write_text(
            """<dialog open><h2>Apply to Example</h2>
          <section id="questions"><h3>Screening</h3>
          <div><label for="salary">Salary*</label><input id="salary" inputmode="numeric"
            value="1,200" maxlength="20" aria-describedby="error">
            <p id="error" hidden>Invalid input</p>
          </div><label for="optional">Optional</label><input id="optional" value="Keep me">
          <button onclick="advance()">Next</button></section>
          <section id="review" hidden><h3>Review application</h3>
          <button onclick="window.submitted=true">Submit application</button></section></dialog>
          <script>window.clicks=0;window.submitted=false;
          function advance(){window.clicks++;const el=document.getElementById('salary');
            if(PERSISTENT || !/^\\d+$/.test(el.value)){
              el.setAttribute('aria-invalid','true');document.getElementById('error').hidden=false;
            }else{document.getElementById('questions').hidden=true;
              document.getElementById('review').hidden=false;}}
          </script>""".replace("PERSISTENT", str(persistent).lower()),
            encoding="utf-8",
        )
        page = await browser.new_page()
        await page.goto(fixture.as_uri())
        outcome = await _task4_on_page(page, browser, None, {}, settings, lambda _: None)
        state = json.loads(
            await page.evaluate("""() => JSON.stringify({
          clicks:window.clicks,submitted:window.submitted,
          salary:document.getElementById('salary').value,
          optional:document.getElementById('optional').value})""")
        )
        assert state == {"clicks": 2, "submitted": False, "salary": "1200", "optional": "Keep me"}
        assert outcome.reached_terminal_step is not persistent
        assert bool(outcome.validation.issues) is persistent
        if persistent:
            assert outcome.validation.correction_attempted
            assert outcome.validation.retry_count == 1
    finally:
        await browser.kill()


async def test_unknown_rejected_answer_does_not_wait_for_human(tmp_path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path / "data",
        session=SessionSettings(
            headless=True,
            ask_human=True,
            post_click_wait_seconds=0,
            easy_apply_timeout_seconds=0.5,
        ),
    )
    browser = build_browser(settings)
    await browser.start()
    try:
        fixture = tmp_path / "unknown.html"
        fixture.write_text(
            """<dialog open><h2>Apply to Example</h2><div>
          <label for="answer">Secret unknown question*</label>
          <input id="answer" aria-invalid="true">
          <p>Invalid input</p></div><button>Next</button></dialog>""",
            encoding="utf-8",
        )
        page = await browser.new_page()
        await page.goto(fixture.as_uri())

        async def unknown(question, kind, options):
            return QuestionDecision(question=question)

        async def forbidden(*args, **kwargs):
            pytest.fail("a rejected unknown answer must be skipped, not sent to a human prompt")

        monkeypatch.setattr(
            "src.tools.linkedin_easy_apply_fill.form_walk.ask_human_for_answer", forbidden
        )
        outcome = await _task4_on_page(
            page,
            browser,
            None,
            {},
            settings,
            lambda _: None,
            chooser=unknown,
        )
        assert outcome.validation.issues
        assert not outcome.validation.retry_count
        assert not outcome.reached_terminal_step
    finally:
        await browser.kill()
