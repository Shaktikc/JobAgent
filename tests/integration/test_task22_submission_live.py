"""Run the real fill and submit code in isolated Chromium, on a controlled form."""

import asyncio
import base64
import gc
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task4Outcome, Task5Outcome
from src.tools import browser as browser_tools
from src.tools.linkedin_apply_loop import await_human_submit
from src.tools.linkedin_auto_submit import _submit_on_page, submit_application
from src.tools.linkedin_easy_apply_fill.form_walk import _task4_on_page
from src.tools.llm_answers import QuestionDecision
from tests.integration.task22_fixture import BODY

pytest.importorskip("browser_use")
pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_SUBMISSION_LIVE"), reason="set AUTOJOB_SUBMISSION_LIVE=1",
)


@pytest.mark.parametrize("reviews,mode", [(0, "auto"), (2, "auto"), (1, "manual")])
async def test_dynamic_form_and_submission_mode(tmp_path, reviews, mode):
    settings = Settings(data_dir=tmp_path / "data", session=SessionSettings(
        headless=True, post_click_wait_seconds=0, ask_human=False,
        keep_open_timeout_seconds=0.3, keep_open_poll_seconds=0.05,
        auto_submit_timeout_seconds=1,
    ))
    browser = browser_tools.build_browser(settings)
    await browser.start()
    run_id = "task22-controlled"
    try:
        file = tmp_path / "task22.html"
        file.write_text(BODY, encoding="utf-8")
        page = await browser.new_page()
        await page.goto(file.as_uri() + f"?reviews={reviews}")
        # Own the browser separately so a manual timeout can detach its run
        # without disconnecting the test's inspection connection.
        browser_tools._ACTIVE_RUNS[run_id] = browser_tools._Run(
            session=SimpleNamespace(is_cdp_connected=True), page=page,
        )
        async def choose(question, kind, options):
            return QuestionDecision(question=question, answer="Immediate")
        outcome = await _task4_on_page(
            page, browser, str(tmp_path / "resume.pdf"), {}, settings, lambda _: None,
            human=Task5Outcome(), chooser=choose,
        )
        assert outcome.reached_terminal_step, outcome.model_dump()
        assert outcome.resume_attached and outcome.resume_selection == "listed"
        assert outcome.steps_advanced == reviews + 2
        assert not outcome.submitted
        assert json.loads(await page.evaluate("() => JSON.stringify(submitClicks)")) == 0
        evidence = Path("data/debug/task22")
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / f"{mode}-{reviews}-review.png").write_bytes(
            base64.b64decode(await page.screenshot()),
        )
        if mode == "auto":
            # The public boundary rejects external/file URLs. The controlled
            # fixture runs the same internal browser path without sending jobs.
            refused = await submit_application(run_id, outcome, settings)
            assert refused.status == "blocked"
            result = await _submit_on_page(page, outcome, settings, print, "Engineer", "Example")
            assert result.status == "submitted", result
            assert outcome.submitted and outcome.submission_attempted
        else:
            assert await await_human_submit(run_id, settings, title="Engineer") == "timeout"
        state = json.loads(await page.evaluate("""() => JSON.stringify({
          clicks:submitClicks,errors:errors,open:document.getElementById('application').open
        })"""))
        assert state == {"clicks": int(mode == "auto"), "errors": [], "open": mode == "manual"}
        (evidence / f"{mode}-{reviews}.json").write_text(
            json.dumps({"browser": state, "outcome": outcome.model_dump()}, indent=2),
            encoding="utf-8",
        )
    finally:
        browser_tools.forget_run(run_id)
        await browser.kill()
        gc.collect()
        await asyncio.sleep(0)


async def test_runtime_blockers_prevent_a_click(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", session=SessionSettings(headless=True))
    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        file = tmp_path / "blocked.html"
        file.write_text(BODY, encoding="utf-8")
        page = await browser.new_page()
        for scenario in ["unknown", "validation", "ambiguous", "disabled", "aria", "invalid"]:
            await page.goto(file.as_uri())
            await page.evaluate("""(scenario) => {
              document.getElementById('answer').value='Immediate'; step('terminal');
              const terminal=document.getElementById('terminal');
              const button=document.getElementById('submit');
              if (scenario==='unknown') terminal.insertAdjacentHTML('afterbegin',
                '<label for="pending">Pending *</label><input id="pending" required>');
              if (scenario==='validation') terminal.insertAdjacentHTML('afterbegin',
                '<div role="alert">Invalid input</div>');
              if (scenario==='ambiguous') terminal.appendChild(button.cloneNode(true));
              if (scenario==='disabled') button.disabled=true;
              if (scenario==='aria') button.setAttribute('aria-disabled','true');
              if (scenario==='invalid') terminal.insertAdjacentHTML('afterbegin',
                '<label for="email">Email *</label><input id="email" type="email" value="bad">');
            }""", scenario)
            outcome = Task4Outcome(form_open=True, reached_terminal_step=True, resume_attached=True)
            result = await _submit_on_page(page, outcome, settings, print)
            assert result.status == "blocked", (scenario, result)
            assert not outcome.submission_attempted
            assert json.loads(await page.evaluate("() => JSON.stringify(submitClicks)")) == 0
    finally:
        await browser.kill()
        gc.collect()
        await asyncio.sleep(0)


async def test_no_confirmation_never_repeats_submit(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", session=SessionSettings(
        headless=True, auto_submit_timeout_seconds=0.2, keep_open_poll_seconds=0.05,
    ))
    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        file = tmp_path / "missing.html"
        file.write_text(BODY, encoding="utf-8")
        page = await browser.new_page()
        await page.goto(file.as_uri() + "?missing=1")
        # Simulate a completed walk; runtime checks still inspect current controls.
        await page.evaluate("""() => {
          document.getElementById('answer').value='Immediate'; step('terminal');
        }""")
        outcome = Task4Outcome(form_open=True, reached_terminal_step=True, resume_attached=True)
        result = await _submit_on_page(page, outcome, settings, print)
        assert result.status == "unconfirmed"
        assert outcome.submission_attempted and not outcome.submitted
        again = await _submit_on_page(page, outcome, settings, print)
        assert again.status == "blocked"
        assert json.loads(await page.evaluate("() => JSON.stringify(submitClicks)")) == 1
    finally:
        await browser.kill()
        gc.collect()
        await asyncio.sleep(0)
