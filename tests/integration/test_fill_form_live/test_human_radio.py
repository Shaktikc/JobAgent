"""Live form human radio checks; see common.py for setup."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.state import Task5Outcome
from src.tools import browser as browser_tools
from src.tools.answers import normalize_question

pytest.importorskip("browser_use")

from .common import _settings
from .common import pytestmark as pytestmark

_TASK5_RADIO_FORM_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Task 5 radio</title></head>
<body>
<div class="artdeco-modal jobs-easy-apply-modal" role="dialog">
  <div class="artdeco-modal__content">
    <div class="jobs-easy-apply-form-section__grouping">
      <span class="fb-form-element-label">
        Have you previously mentored, reviewed the work of, or provided technical
        direction to more junior engineers?*
      </span>
      <div class="fb-form-element-wrapper">
        <div class="fb-dash-form-element" role="radio" aria-checked="false"
             data-option="Yes"><span>Yes</span></div>
        <div class="fb-dash-form-element" role="radio" aria-checked="false"
             data-option="No"><span>No</span></div>
      </div>
    </div>
  </div>
  <footer class="artdeco-modal__actionbar">
    <button type="button" id="submit-btn" style="display:none">Submit application</button>
  </footer>
</div>
<script>
  document.querySelectorAll('[role="radio"]').forEach(function (r) {
    r.addEventListener('click', function () {
      document.querySelectorAll('[role="radio"]').forEach(function (x) {
        x.setAttribute('aria-checked', 'false');
      });
      r.setAttribute('aria-checked', 'true');
    });
  });
</script>
</body></html>
"""

# Play the human: click the choice the way a mouse would (fires only ``click``).
_CLICK_RADIO_JS = """(option) => {
  const r = Array.from(document.querySelectorAll('[role="radio"]'))
    .find((x) => (x.getAttribute('data-option') || '') === option);
  if (!r) return false;
  r.click();
  return true;
}"""


async def test_task5_reads_a_role_radio_choice_and_stores_it(tmp_path: Path) -> None:
    """A ``role=radio`` screening question is answered by a click and remembered.

    LinkedIn renders these as styled divs, so a click fires no ``input``/``change``;
    the watcher must still capture the choice and store the answer right away.
    """
    settings = _settings(tmp_path, ask_human=True)

    form_file = tmp_path / "task5_radio.html"
    form_file.write_text(_TASK5_RADIO_FORM_HTML, encoding="utf-8")

    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(form_file.as_uri())
        await browser_tools._wait_for_load(page, 10)

        human = Task5Outcome()
        fill_task = asyncio.create_task(
            browser_tools._task4_on_page(
                page, browser, None, {}, settings, lambda _m: None, human=human
            )
        )

        banner_present = False
        for _ in range(200):
            payload = json.loads(await page.evaluate(browser_tools._READ_UNKNOWN_JS))
            if payload.get("present"):
                banner_present = True
                break
            await asyncio.sleep(0.05)
        assert banner_present, "the Task 5 banner never appeared"

        clicked = await page.evaluate(_CLICK_RADIO_JS, "Yes")
        assert str(clicked).lower() == "true"
        outcome = await asyncio.wait_for(fill_task, timeout=30)

        assert outcome.submitted is False
        assert human.answered == 1
        stored = browser_tools.load_answers(settings.answers_file)
        key = normalize_question(
            "Have you previously mentored, reviewed the work of, or provided "
            "technical direction to more junior engineers?"
        )
        assert stored[key] == "Yes"
    finally:
        await browser.kill()

_NATIVE_RADIO_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Task 5 native radio</title></head>
<body>
<div class="artdeco-modal jobs-easy-apply-modal" role="dialog">
  <div class="artdeco-modal__content">
    <div class="jobs-easy-apply-form-section__grouping">
      <span class="fb-form-element-label">Will you now or in the future require
        sponsorship for employment visa status?*</span>
      <div class="fb-form-element-wrapper">
        <div class="fb-dash-form-element">
          <input type="radio" name="sponsor" value=""><span>Yes</span>
        </div>
        <div class="fb-dash-form-element">
          <input type="radio" name="sponsor" value=""><span>No</span>
        </div>
      </div>
    </div>
  </div>
  <footer class="artdeco-modal__actionbar">
    <button type="button" id="submit-btn" style="display:none">Submit application</button>
  </footer>
</div>
</body></html>
"""

_CLICK_NATIVE_RADIO_JS = """(option) => {
  const el = Array.from(document.querySelectorAll('input[type=radio][name="sponsor"]'))
    .find((x) => x.nextElementSibling && x.nextElementSibling.textContent.trim() === option);
  if (!el) return false;
  el.click();
  return true;
}"""


async def test_task5_reads_a_native_radio_whose_option_text_is_a_sibling(
    tmp_path: Path,
) -> None:
    """A styled native radio (option text in a sibling span) is captured and stored."""
    settings = _settings(tmp_path, ask_human=True)

    form_file = tmp_path / "native_radio.html"
    form_file.write_text(_NATIVE_RADIO_HTML, encoding="utf-8")

    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(form_file.as_uri())
        await browser_tools._wait_for_load(page, 10)

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

        # The option text is read from the sibling span, not the question label.
        banner_text = await page.evaluate(
            "() => document.getElementById('autojob-unknown').innerText"
        )
        assert "One of: Yes, No" in banner_text

        assert str(await page.evaluate(_CLICK_NATIVE_RADIO_JS, "No")).lower() == "true"
        await asyncio.wait_for(fill_task, timeout=30)

        assert human.answered == 1
        stored = browser_tools.load_answers(settings.answers_file)
        key = normalize_question(
            "Will you now or in the future require sponsorship for employment visa status?"
        )
        assert stored[key] == "No"
    finally:
        await browser.kill()

_LINKEDIN_ROLE_RADIO_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Task 5 LinkedIn radio</title></head>
<body>
<div class="artdeco-modal jobs-easy-apply-modal" role="dialog">
  <div class="artdeco-modal__content">
    <p>Do you have full, unrestricted working rights in Australia with no expiration date?*</p>
    <div class="hcbwrap">
      <div role="radio" tabindex="0" aria-checked="false" data-option="Yes"
           aria-label="Do you have full, unrestricted working rights in Australia
                       with no expiration date?*">
        <div><div>
          <input id="_r_1j_" type="radio" name="radio-group-_r_1g_">
          <label for="_r_1j_"></label>
        </div><div><p>Yes</p></div></div>
      </div>
      <div role="radio" tabindex="0" aria-checked="false" data-option="No"
           aria-label="Do you have full, unrestricted working rights in Australia
                       with no expiration date?*">
        <div><div>
          <input id="_r_1i_" type="radio" name="radio-group-_r_1g_">
          <label for="_r_1i_"></label>
        </div><div><p>No</p></div></div>
      </div>
    </div>
  </div>
  <footer class="artdeco-modal__actionbar">
    <button type="button" id="submit-btn" style="display:none">Submit application</button>
  </footer>
</div>
<script>
  document.querySelectorAll('[role="radio"]').forEach(function (r) {
    r.addEventListener('click', function () {
      const group = r.parentElement;
      group.querySelectorAll('[role="radio"]').forEach(function (x) {
        x.setAttribute('aria-checked', 'false');
        const i = x.querySelector('input');
        if (i) { i.checked = false; i.removeAttribute('checked'); }
      });
      r.setAttribute('aria-checked', 'true');
      const input = r.querySelector('input');
      if (input) { input.checked = true; input.setAttribute('checked', ''); }
      // React-like re-render of the selected node: a fresh node without our marker.
      if (r.getAttribute('data-autojob-fill')) {
        r.replaceWith(r.cloneNode(true));
      }
    });
  });
</script>
</body></html>
"""

_CLICK_ROLE_RADIO_BY_TEXT_JS = """(option) => {
  const r = Array.from(document.querySelectorAll('[role="radio"]'))
    .find((x) => (x.getAttribute('data-option') || '') === option);
  if (!r) return false;
  r.click();
  return true;
}"""


async def test_task5_reads_linkedin_role_radio_and_its_inner_input(tmp_path: Path) -> None:
    """Read the option from the wrapper text and the state via the input's name."""
    settings = _settings(tmp_path, ask_human=True)

    form_file = tmp_path / "linkedin_radio.html"
    form_file.write_text(_LINKEDIN_ROLE_RADIO_HTML, encoding="utf-8")

    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(form_file.as_uri())
        await browser_tools._wait_for_load(page, 10)

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

        # The option text comes from the wrapper's visible text, not its aria-label
        # (which is the question).
        banner_text = await page.evaluate(
            "() => document.getElementById('autojob-unknown').innerText"
        )
        assert "One of: Yes, No" in banner_text

        assert str(await page.evaluate(_CLICK_ROLE_RADIO_BY_TEXT_JS, "No")).lower() == "true"
        await asyncio.wait_for(fill_task, timeout=30)

        assert human.answered == 1
        stored = browser_tools.load_answers(settings.answers_file)
        key = normalize_question(
            "Do you have full, unrestricted working rights in Australia with no expiration date?"
        )
        assert stored[key] == "No"
    finally:
        await browser.kill()
