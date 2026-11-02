"""Task 21: skip an optional-only step, preserve values, and still answer required fields."""

import asyncio
import gc
import json
import os

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task5Outcome
from src.tools.answers import load_answers
from src.tools.browser import build_browser
from src.tools.linkedin_easy_apply_fill.form_walk import _task4_on_page
from src.tools.llm_answers import QuestionDecision

pytest.importorskip("browser_use")
pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_REQUIRED_LIVE"), reason="set AUTOJOB_REQUIRED_LIVE=1"
)

BODY = """<!doctype html><dialog open><h2>Apply to Example</h2>
  <section id="optional-step">
    <label for="text">Extra details</label><input id="text" value="Keep text" required>
    <label for="area">Introduction</label><textarea id="area" required>Keep prose</textarea>
    <label for="select">Preferred team</label><select id="select" required>
      <option>Keep selection</option><option>Other</option></select>
    <fieldset aria-required="true" aria-describedby="error-message-radio">
      <legend>Travel preference</legend>
      <label><input type="radio" name="travel" checked value="keep">Keep radio</label>
      <label><input type="radio" name="travel" value="other">Other</label></fieldset>
    <p>Extra interests</p><fieldset aria-describedby="error-message-check">
      <label><input type="checkbox" checked>Keep checked</label>
      <label><input type="checkbox">Keep unchecked</label></fieldset>
    <label for="empty">Unanswered details</label><input id="empty" aria-required="true">
    <button type="button" onclick="document.getElementById('optional-step').hidden=true;
      document.getElementById('required-step').hidden=false">Next</button>
  </section>
  <section id="required-step" hidden>
    <label for="required">Availability *</label><input id="required" required>
    <button type="button" onclick="window.submitted=true">Submit application</button>
  </section></dialog>
  <script>window.changes=[]; window.submitted=false;
  document.getElementById('optional-step').addEventListener('change',
    e => changes.push(e.target.id));
  </script>"""

SNAPSHOT = """() => JSON.stringify({
  values:Array.from(document.querySelectorAll('#optional-step input, '
    + '#optional-step textarea, #optional-step select')).map(e => [e.value,e.checked]),
  changes:window.changes, submitted:window.submitted
})"""


@pytest.mark.parametrize("known", [True, False])
async def test_optional_only_step_advances_and_required_fill_or_human_prompt_still_works(
    tmp_path, known
):
    settings = Settings(data_dir=tmp_path / "data", session=SessionSettings(
        headless=True, post_click_wait_seconds=0, ask_human=True,
        ask_timeout_seconds=12, ask_poll_seconds=0.1,
    ))
    browser = build_browser(settings)
    await browser.start()
    task = None
    try:
        file = tmp_path / "optional_walk.html"
        file.write_text(BODY, encoding="utf-8")
        page = await browser.new_page()
        await page.goto(file.as_uri())
        before = json.loads(await page.evaluate(SNAPSHOT))
        calls = []

        async def choose(question, kind, options):
            calls.append(question)
            assert question == "Availability *", "optional question reached the chooser"
            return QuestionDecision(question=question, answer="Immediate" if known else None)

        human = Task5Outcome()
        # Include a remembered optional answer: the entire lookup/selection path
        # must be bypassed, and an existing optional tick must not be persisted.
        answers = {"extra details": "Overwrite would be a bug"}
        task = asyncio.create_task(_task4_on_page(
            page, browser, None, answers, settings, lambda _: None, human=human, chooser=choose,
        ))
        if not known:
            for _ in range(100):
                banner = json.loads(await page.evaluate(
                    "() => JSON.stringify({visible:!!document.getElementById('autojob-unknown')})"
                ))
                if banner["visible"]:
                    break
                if task.done():
                    await task
                    pytest.fail("required question never showed a human banner")
                await asyncio.sleep(0.1)
            else:
                pytest.fail("required question never showed a human banner")
            # Paste the complete answer in one event, as a human can do, so
            # Task 5's immediate-save behavior cannot observe half-typed text.
            await page.evaluate("""() => {
              const el = document.getElementById('required');
              el.value = 'Immediate';
              el.dispatchEvent(new Event('input', {bubbles:true}));
              el.dispatchEvent(new Event('change', {bubbles:true}));
              el.dispatchEvent(new Event('blur', {bubbles:true}));
            }""")
        outcome = await asyncio.wait_for(task, timeout=20)
        after = json.loads(await page.evaluate(SNAPSHOT))
        assert after == before
        assert calls == ["Availability *"]
        assert outcome.steps_advanced == 1
        assert outcome.reached_terminal_step and not outcome.submitted
        assert outcome.unknown_fields == []
        assert outcome.filled_fields == outcome.known_fields == 1
        assert [f.question for f in outcome.fields] == ["Availability *"]
        assert human.asked == (0 if known else 1)
        assert human.timed_out == 0
        stored = load_answers(settings.answers_file)
        assert stored == ({} if known else {"availability": "Immediate"})
    finally:
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await browser.kill()
        gc.collect()
        await asyncio.sleep(0)
