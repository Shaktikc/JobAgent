"""Live form human text checks; see common.py for setup."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.state import Task5Outcome
from src.tools import browser as browser_tools

pytest.importorskip("browser_use")

from .common import _RESUME_NAME, _settings
from .common import pytestmark as pytestmark

_TASK5_FORM_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Task 5</title></head>
<body>
<div class="artdeco-modal jobs-easy-apply-modal" role="dialog">
  <div class="artdeco-modal__content">
    <div class="fb-dash-form-element">
      <label for="email">Email address*</label>
      <select id="email" name="email" required>
        <option value="me@example.com" selected>me@example.com</option>
      </select>
    </div>
    <div class="fb-dash-form-element">
      <label for="notice">Notice period*</label>
      <input id="notice" name="notice" type="text" required>
    </div>
  </div>
  <footer class="artdeco-modal__actionbar">
    <button type="button" id="submit-btn" style="display:none">Submit application</button>
  </footer>
</div>
</body></html>
"""

# Play the human: type the answer into the real form field (the banner has no
# input) and fire the events a real edit would, so the agent picks it up.
_ANSWER_IN_FORM_JS = """(answer) => {
  const el = document.getElementById('notice');
  if (!el) return false;
  el.focus();
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value'
  ).set;
  setter.call(el, answer);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  el.blur();
  return true;
}"""

_READ_TASK5_JS = """() => JSON.stringify({
  notice_value: (() => {
    const el = document.getElementById('notice');
    return el ? el.value : '';
  })(),
  email_value: (() => {
    const el = document.getElementById('email');
    return el ? el.value : '';
  })(),
  banner_present: !!document.getElementById('autojob-unknown')
})"""


async def test_task5_pauses_for_the_human_and_remembers(tmp_path: Path) -> None:
    """A real browser shows the banner, waits, then stores the human's answer."""
    settings = _settings(tmp_path, ask_human=True)
    resume_file = tmp_path / "resumes" / _RESUME_NAME
    resume_file.parent.mkdir(parents=True, exist_ok=True)
    resume_file.write_text("Senior Python engineer", encoding="utf-8")

    form_file = tmp_path / "task5.html"
    form_file.write_text(_TASK5_FORM_HTML, encoding="utf-8")

    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(form_file.as_uri())
        await browser_tools._wait_for_load(page, 10)

        human = Task5Outcome()
        fill_task = asyncio.create_task(
            browser_tools._task4_on_page(
                page,
                browser,
                str(resume_file),
                {},
                settings,
                lambda _m: None,
                human=human,
            )
        )

        # Wait until the agent pauses on the banner, then act as the human.
        banner_present = False
        for _ in range(200):
            payload = json.loads(await page.evaluate(browser_tools._READ_UNKNOWN_JS))
            if payload.get("present"):
                banner_present = True
                break
            await asyncio.sleep(0.05)
        assert banner_present, "the Task 5 banner never appeared"

        banner_text = await page.evaluate(
            "() => document.getElementById('autojob-unknown').innerText"
        )
        assert "does not know" in banner_text
        assert "Notice period" in banner_text
        # The banner only explains the problem: it has no answer input of its own.
        has_input = await page.evaluate(
            "() => !!document.getElementById('autojob-unknown-input')"
        )
        assert str(has_input).lower() == "false"

        # An empty edit must not silently skip the question: the banner stays open
        # and waits for a real answer typed into the form.
        await page.evaluate(_ANSWER_IN_FORM_JS, "")
        await asyncio.sleep(0.4)
        still_open = json.loads(await page.evaluate(browser_tools._READ_UNKNOWN_JS))
        assert still_open["present"] is True

        # Typing into the real form field is what the agent reads.
        await page.evaluate(_ANSWER_IN_FORM_JS, "4 weeks")
        outcome = await asyncio.wait_for(fill_task, timeout=30)

        observed = json.loads(await page.evaluate(_READ_TASK5_JS))
        assert observed["notice_value"] == "4 weeks"
        assert observed["banner_present"] is False
        assert outcome.submitted is False

        # The pre-filled email select was left untouched and never asked about.
        assert observed["email_value"] == "me@example.com"

        assert human.enabled is True
        assert human.asked == 1
        assert human.answered == 1
        assert human.skipped == 0
        assert human.answered_questions == ["Notice period*"]
        stored = browser_tools.load_answers(settings.answers_file)
        assert stored["notice period"] == "4 weeks"
        assert "email address" not in stored
    finally:
        await browser.kill()
