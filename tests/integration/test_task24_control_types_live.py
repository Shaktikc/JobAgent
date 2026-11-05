"""Every required control kind survives a replacement of the marked DOM."""

import json
import os

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task4Outcome, Task5Outcome
from src.tools.browser import build_browser
from src.tools.linkedin_easy_apply_fill.form_queries import read_form, read_form_buttons
from src.tools.linkedin_easy_apply_fill.form_walk import _blur_active, _form_signature
from src.tools.linkedin_validation.navigation import finish_advance
from src.tools.linkedin_validation.required_answers import AnswerAttempts
from src.tools.llm_answers import QuestionDecision

pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_FILL_LIVE"),
    reason="set AUTOJOB_FILL_LIVE=1",
)


@pytest.mark.parametrize(
    ("control", "answer"),
    [
        ('<label for="a">Experience*</label><input id="a">', "Two years"),
        ('<label for="a">Experience*</label><textarea id="a"></textarea>', "Two years"),
        (
            '<label for="a">Experience*</label><select id="a"><option disabled selected value="">'
            'Select an option</option><option value="two">Two years</option></select>',
            "Two years",
        ),
        (
            '<legend>Experience*</legend><label><input type="radio" name="a" value="y">Yes</label>'
            '<label><input type="radio" name="a" value="n">No</label>',
            "Yes",
        ),
        (
            '<legend>Experience*</legend><label><input type="checkbox" name="a">Red</label>'
            '<label><input type="checkbox" name="b">Blue</label>',
            "Red, Blue",
        ),
    ],
)
async def test_recovery_verifies_replaced_controls(tmp_path, control, answer):
    settings = Settings(
        data_dir=tmp_path / "data",
        session=SessionSettings(
            headless=True,
            ask_human=False,
            easy_apply_timeout_seconds=0.1,
            post_click_wait_seconds=0,
        ),
    )
    browser = build_browser(settings)
    await browser.start()
    try:
        fixture = tmp_path / "types.html"
        fixture.write_text(
            """<dialog open><h2>Apply to Example</h2>
          <section id="step"><fieldset onchange="replace(this)">CONTROL
            <p role="alert">This field is required</p></fieldset>
            <button onclick="advance()">Review</button></section>
          <section hidden id="review"><h3>Review application</h3>
            <button onclick="window.submitted=true">Submit application</button></section>
          </dialog><script>window.replaced=0; window.submitted=false;
          function replace(el){window.replaced++;const copy=el.cloneNode(true);
            el.querySelectorAll('select').forEach((n,i)=>
              copy.querySelectorAll('select')[i].value=n.value);
            copy.querySelectorAll('[data-autojob-fill]').forEach(n=>n.removeAttribute('data-autojob-fill'));
            el.replaceWith(copy);}
          function advance(){document.getElementById('step').hidden=true;
            document.getElementById('review').hidden=false;}</script>""".replace(
                "CONTROL", control
            ),
            encoding="utf-8",
        )
        page = await browser.new_page(fixture.as_uri())
        current = await read_form(page)

        async def choose(question, kind, options):
            return QuestionDecision(question=question, answer=answer, source_keys=["experience"])

        previous = _form_signature(current[1], current[2], current[3])
        attempts = AnswerAttempts(settings, Task5Outcome(), choose, None, lambda _: None)
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
        assert not outcome.validation.issues
        assert _form_signature(final[1], final[2], final[3]) != previous
        assert outcome.filled_fields == 1
        state = json.loads(
            await page.evaluate(
                "() => JSON.stringify({replaced:window.replaced,submitted:window.submitted})"
            )
        )
        assert state["replaced"] > 0 and not state["submitted"]
    finally:
        await browser.kill()
