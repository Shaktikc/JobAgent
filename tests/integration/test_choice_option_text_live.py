"""Opt-in live-browser regression for reading a choice option's visible text.

BUG-082: LinkedIn's current SDUI radio layout renders each option as a native
``input[type=radio]`` whose associated ``label[for]`` is empty, while the input's
``aria-label`` is the **question** and the visible option text ("Yes"/"No") sits
in a sibling block of the next ancestor. The old reader fell back to the
aria-label, so the banner listed the question twice and the store saved the
question as the human's answer instead of the option they selected.

The fixture below is the exact shape observed on the live LinkedIn form. The test
drives the real Task 4 enumeration + Task 5 wait/store path in Chromium: the
banner must list "Yes, No", clicking the option *text* must be captured, and the
store must receive "Yes" rather than the question.

Enable it (the ``browser`` extra must be installed)::

    $env:AUTOJOB_FILL_LIVE="1"
    uv run pytest tests/integration/test_choice_option_text_live.py -s

Skipped by default so the unit suite stays fast and offline.
"""

from __future__ import annotations

import asyncio
import gc
import json
import os
from pathlib import Path

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task5Outcome
from src.tools import browser as browser_tools
from src.tools.answers import normalize_question
from src.tools.linkedin_ask_human.answer_js import _WATCH_FORM_ANSWER_JS
from src.tools.llm_answers import QuestionDecision

pytest.importorskip("browser_use")

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("AUTOJOB_FILL_LIVE"),
        reason="set AUTOJOB_FILL_LIVE=1 to run the live choice-option test",
    ),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

QUESTION = "Are you happy coming to the office 2-3 days per week?*"

_FORM_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Choice options</title></head>
<body>
<div class="artdeco-modal jobs-easy-apply-modal" role="dialog">
  <div class="artdeco-modal__content">
    <div class="jobs-easy-apply-form-section__grouping">
      <span class="fb-form-element-label">__QUESTION__</span>
      <fieldset role="radiogroup">
        <div class="option-row">
          <div class="circle">
            <input id="office-yes" type="radio" name="office"
                   aria-label="__BARE_QUESTION__">
            <label for="office-yes"></label>
          </div>
          <div class="option-text"><p>Yes</p></div>
        </div>
        <div class="option-row">
          <div class="circle">
            <input id="office-no" type="radio" name="office"
                   aria-label="__BARE_QUESTION__">
            <label for="office-no"></label>
          </div>
          <div class="option-text"><p>No</p></div>
        </div>
      </fieldset>
    </div>
  </div>
  <footer class="artdeco-modal__actionbar">
    <button type="button" id="submit-btn" style="display:none">
      Submit application
    </button>
  </footer>
</div>
<script>
  window.__picked = '';
  window.__submitted = false;
  function pick(row) {
    const input = row.querySelector('input[type=radio]');
    if (!input) return;
    document.querySelectorAll('input[name="office"]').forEach(function (radio) {
      radio.checked = false;
    });
    input.checked = true;
    window.__picked = row.querySelector('p').textContent.trim();
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }
  document.querySelectorAll('.option-row').forEach(function (row) {
    row.addEventListener('click', function () { pick(row); });
  });
  window.__clickOptionText = function (text) {
    const target = Array.from(document.querySelectorAll('.option-row p'))
      .find(function (node) { return node.textContent.trim() === text; });
    if (!target) return false;
    target.click();
    return true;
  };
  document.getElementById('submit-btn').addEventListener('click', function () {
    window.__submitted = true;
  });
</script>
</body></html>
"""


def _settings(tmp_path: Path) -> Settings:
    headless = os.environ.get("AUTOJOB_SESSION_HEADLESS", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    return Settings(
        session=SessionSettings(
            headless=headless,
            ask_human=True,
            ask_timeout_seconds=30.0,
            ask_poll_seconds=0.1,
            post_click_wait_seconds=0.0,
        ),
        data_dir=tmp_path / "data",
    )


_READ_STATE_JS = """() => JSON.stringify({
  picked: window.__picked,
  submitted: window.__submitted === true,
  checked: Array.from(document.querySelectorAll('input[name="office"]'))
    .filter((el) => el.checked)
    .map((el) => el.id)
})"""

# Two independent questions with the same new-style option rows. Clicking the
# second question's text must never answer the first question's watcher (the
# BUG-037 scope rule still has to hold after the option-text fix).
_TWO_GROUPS_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Two choice groups</title></head>
<body>
<div class="question">
  <div class="row" data-group="a">
    <div class="circle">
      <input id="a-yes" type="radio" name="a" aria-label="Question A?">
      <label for="a-yes" data-autojob-fill="a1"></label>
    </div>
    <div><p>Yes</p></div>
  </div>
  <div class="row" data-group="a">
    <div class="circle">
      <input id="a-no" type="radio" name="a" aria-label="Question A?">
      <label for="a-no" data-autojob-fill="a2"></label>
    </div>
    <div><p>No</p></div>
  </div>
</div>
<div class="question">
  <div class="row" data-group="b">
    <div class="circle">
      <input id="b-yes" type="radio" name="b" aria-label="Question B?">
      <label for="b-yes" data-autojob-fill="b1"></label>
    </div>
    <div><p>Yes</p></div>
  </div>
  <div class="row" data-group="b">
    <div class="circle">
      <input id="b-no" type="radio" name="b" aria-label="Question B?">
      <label for="b-no" data-autojob-fill="b2"></label>
    </div>
    <div><p>No</p></div>
  </div>
</div>
<script>
  document.querySelectorAll('.row').forEach(function (row) {
    row.addEventListener('click', function () {
      const input = row.querySelector('input[type=radio]');
      if (!input) return;
      document.querySelectorAll('input[name="' + input.name + '"]').forEach(
        function (radio) { radio.checked = false; }
      );
      input.checked = true;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });
  window.__clickOption = function (group, text) {
    const row = Array.from(document.querySelectorAll('.row')).find(function (item) {
      return item.getAttribute('data-group') === group
        && item.querySelector('p').textContent.trim() === text;
    });
    if (!row) return false;
    row.querySelector('p').click();
    return true;
  };
</script>
</body></html>
"""


async def _open_page(tmp_path: Path, settings: Settings, html: str, name: str):
    form_file = tmp_path / name
    form_file.write_text(html, encoding="utf-8")
    browser = browser_tools.build_browser(settings)
    await browser.start()
    page = await browser.new_page()
    await page.goto(form_file.as_uri())
    await browser_tools._wait_for_load(page, 10)
    return browser, page


async def _open_fixture(tmp_path: Path, settings: Settings):
    html = (
        _FORM_HTML.replace("__QUESTION__", QUESTION)
        .replace("__BARE_QUESTION__", QUESTION.rstrip("*"))
    )
    return await _open_page(tmp_path, settings, html, "choice_options.html")


async def test_enumeration_reads_the_option_text_not_the_question(tmp_path: Path) -> None:
    """The field options are "Yes"/"No", never the question in the aria-label."""
    settings = _settings(tmp_path)
    browser, page = await _open_fixture(tmp_path, settings)
    try:
        opened, _title, fields, _step = await browser_tools.read_form(page)
        radios = [field for field in fields if field["kind"] == "radio"]
        assert opened is True
        assert [field["option"] for field in radios] == ["Yes", "No"]
        assert {field["question"] for field in radios} == {QUESTION}
    finally:
        await browser.kill()
        gc.collect()


async def test_clicking_option_text_stores_that_option(tmp_path: Path) -> None:
    """Task 5 lists Yes/No, captures a click on the text, and stores "Yes"."""
    settings = _settings(tmp_path)
    browser, page = await _open_fixture(tmp_path, settings)
    try:
        human = Task5Outcome()
        fill_task = asyncio.create_task(
            browser_tools._task4_on_page(
                page, browser, None, {}, settings, lambda _m: None, human=human
            )
        )

        appeared = False
        for _ in range(200):
            payload = json.loads(await page.evaluate(browser_tools._READ_UNKNOWN_JS))
            if payload.get("present"):
                appeared = True
                break
            await asyncio.sleep(0.05)
        assert appeared, "the Task 5 banner never appeared"

        banner = await page.evaluate(
            "() => document.getElementById('autojob-unknown').innerText"
        )
        assert "One of: Yes, No" in banner, banner
        assert "One of: " + QUESTION.rstrip("*") not in banner

        assert str(await page.evaluate("() => window.__clickOptionText('Yes')")).lower() == (
            "true"
        )
        outcome = await asyncio.wait_for(fill_task, timeout=30)
        state = json.loads(await page.evaluate(_READ_STATE_JS))
        stored = browser_tools.load_answers(settings.answers_file)

        key = normalize_question(QUESTION)
        assert stored[key] == "Yes"
        assert stored[key] != QUESTION.rstrip("*")
        assert human.asked == 1 and human.answered == 1
        assert state["picked"] == "Yes"
        assert state["checked"] == ["office-yes"]
        assert state["submitted"] is False
        assert outcome.submitted is False
        record = outcome.fields[0]
        assert record.value == "Yes"
        assert record.filled is True
    finally:
        await browser.kill()
        gc.collect()


async def test_stored_answer_fills_the_new_native_radio(tmp_path: Path) -> None:
    """With correct option labels, a remembered "Yes" is applied without a prompt."""

    async def chooser(
        question: str, field_type: str, options: list[str]
    ) -> QuestionDecision:
        assert options == ["Yes", "No"]
        return QuestionDecision(
            question=question,
            category="test",
            answer="Yes",
            matched_key=normalize_question(QUESTION),
            rationale="test chooser",
        )

    settings = _settings(tmp_path)
    browser, page = await _open_fixture(tmp_path, settings)
    try:
        human = Task5Outcome()
        outcome = await asyncio.wait_for(
            browser_tools._task4_on_page(
                page,
                browser,
                None,
                {normalize_question(QUESTION): "Yes"},
                settings,
                lambda _m: None,
                human=human,
                chooser=chooser,
            ),
            timeout=30,
        )
        state = json.loads(await page.evaluate(_READ_STATE_JS))

        assert human.asked == 0
        assert state["checked"] == ["office-yes"]
        assert state["picked"] == "Yes"
        assert outcome.submitted is False
        record = outcome.fields[0]
        assert record.value == "Yes"
        assert record.filled is True and record.error == ""
    finally:
        await browser.kill()
        gc.collect()


async def test_watcher_ignores_another_questions_option_row(tmp_path: Path) -> None:
    """A click in a different question's row must not leak into this answer."""
    settings = _settings(tmp_path)
    browser, page = await _open_page(
        tmp_path, settings, _TWO_GROUPS_HTML, "two_groups.html"
    )
    try:
        await page.evaluate(_WATCH_FORM_ANSWER_JS, ["a1", "a2"])

        assert str(await page.evaluate("() => window.__clickOption('b', 'Yes')")).lower() == (
            "true"
        )
        await asyncio.sleep(0.1)
        state = json.loads(
            await page.evaluate("() => JSON.stringify(window.__autojobFormAnswer)")
        )
        assert state["value"] == ""
        assert state["done"] is False

        assert str(await page.evaluate("() => window.__clickOption('a', 'Yes')")).lower() == (
            "true"
        )
        await asyncio.sleep(0.1)
        state = json.loads(
            await page.evaluate("() => JSON.stringify(window.__autojobFormAnswer)")
        )
        assert state["value"] == "Yes"
        assert state["done"] is True
    finally:
        await browser.kill()
        gc.collect()
