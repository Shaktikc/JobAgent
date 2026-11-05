"""Real Chromium recovery of a required radio through Next/Review."""

import json
import os

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task4Outcome, Task5Outcome
from src.tools.browser import build_browser
from src.tools.linkedin_ask_human import ask_human_for_answer
from src.tools.linkedin_easy_apply_fill.form_queries import read_form, read_form_buttons
from src.tools.linkedin_easy_apply_fill.form_walk import _blur_active, _form_signature
from src.tools.linkedin_validation.navigation import finish_advance
from src.tools.linkedin_validation.required_answers import AnswerAttempts
from src.tools.llm_answers import QuestionDecision

pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_FILL_LIVE"), reason="set AUTOJOB_FILL_LIVE=1"
)


@pytest.mark.parametrize("persistent", [False, True])
@pytest.mark.parametrize("source", ["automatic", "human"])
async def test_required_radio_is_answered_and_retried_once(
    tmp_path, persistent, source, monkeypatch
):
    settings = Settings(
        data_dir=tmp_path / "data",
        session=SessionSettings(
            headless=True,
            ask_human=source == "human",
            ask_poll_seconds=0.02,
            ask_timeout_seconds=2,
            easy_apply_timeout_seconds=0.1,
            post_click_wait_seconds=0,
        ),
    )
    browser = build_browser(settings)
    await browser.start()
    try:
        fixture = tmp_path / "required.html"
        fixture.write_text(
            """<dialog open><h2>Apply to Example</h2>
          <section id="step"><fieldset><legend>Daily tools*</legend>
            <label><input type="radio" name="tools" value="yes">Yes</label>
            <label><input type="radio" name="tools" value="no">No</label>
            <p role="alert">This field is required</p></fieldset>
          <div style="height:1500px"></div>
          <button onclick="advance()">Review</button></section>
          <section id="review" hidden><h3>Review application</h3>
            <button onclick="window.submitted=true">Submit application</button></section>
          </dialog><script>window.clicks=0;window.submitted=false;
          function advance(){window.clicks++;if(!PERSISTENT &&
            document.querySelector('input:checked')){
            document.getElementById('step').hidden=true;
            document.getElementById('review').hidden=false;}}</script>""".replace(
                "PERSISTENT", str(persistent).lower()
            ),
            encoding="utf-8",
        )
        page = await browser.new_page(fixture.as_uri())
        current = await read_form(page)
        calls = []

        async def choose(question, kind, options):
            calls.append(question)
            return QuestionDecision(
                question=question,
                answer="Yes" if source == "automatic" else None,
                source_keys=["daily tools"],
            )

        monkeypatch.setattr("src.tools.linkedin_ask_human.flow._SAVED_VISIBLE_SECONDS", 0)

        async def ask(question, field):
            # Local test fixture only: simulate an explicit human selection after
            # the real Task 5 watcher/banner has been installed.
            await page.evaluate("""() => setTimeout(() => {
              document.querySelector('input[value="yes"]').click();
            }, 100)""")
            return await ask_human_for_answer(
                page,
                question,
                "radio",
                "Yes, No",
                settings,
                lambda _: None,
                markers=field["markers"],
                name=field["name"],
                options=field["options"],
            )

        attempts = AnswerAttempts(settings, Task5Outcome(), choose, ask, lambda _: None)
        previous = _form_signature(current[1], current[2], current[3])
        attempts.step = previous
        outcome = Task4Outcome()
        final = await finish_advance(
            page,
            current,
            previous,
            settings,
            lambda _: None,
            outcome,
            choose,
            {},
            read=read_form,
            buttons=read_form_buttons,
            signature_of=_form_signature,
            blur=_blur_active,
            required_attempts=attempts,
        )
        assert bool(outcome.validation.issues) is persistent
        assert (_form_signature(final[1], final[2], final[3]) != previous) is not persistent
        assert calls == ["Daily tools*"]
        state = json.loads(
            await page.evaluate(
                "() => JSON.stringify({clicks:window.clicks, submitted:window.submitted})"
            )
        )
        assert state == {"clicks": 1, "submitted": False}
    finally:
        await browser.kill()
