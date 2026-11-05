"""Task 26 completion regressions using Chromium and the production DOM scripts."""

import json
import os

import pytest

from src.configuration import SessionSettings, Settings
from src.tools.browser import build_browser
from src.tools.linkedin_ask_human.answer_js import _READ_FORM_ANSWER_JS, _WATCH_FORM_ANSWER_JS
from src.tools.linkedin_ask_human.banner_js import _SHOW_UNKNOWN_JS
from src.tools.linkedin_ask_human.completion_js import _UPDATE_PENDING_JS

pytestmark = pytest.mark.skipif(not os.environ.get("AUTOJOB_FILL_LIVE"), reason="live opt-in")


@pytest.fixture
async def page(tmp_path):
    browser = build_browser(Settings(data_dir=tmp_path, session=SessionSettings(headless=True)))
    await browser.start()
    fixture = tmp_path / "completion.html"
    fixture.write_text("""<label>Answer<input id="a" data-autojob-fill="a"></label>
      <fieldset><legend>Tools</legend>
      <label><input type="checkbox" name="tools" id="red">Red</label>
      <label><input type="checkbox" name="tools" id="blue">Blue</label></fieldset>""")
    try:
        yield await browser.new_page(fixture.as_uri())
    finally:
        await browser.kill()


async def read(page, markers=None, name="", question="Answer", options=None):
    result = json.loads(
        await page.evaluate(_READ_FORM_ANSWER_JS, markers or ["a"], name, question, options or [])
    )
    await page.evaluate(_UPDATE_PENDING_JS, result["value"])
    return result


async def test_done_disabled_until_value_and_clear_discards_old_value(page):
    await page.evaluate(_WATCH_FORM_ANSWER_JS, ["a"])
    await page.evaluate(_SHOW_UNKNOWN_JS, "Answer", "")
    await read(page)
    assert (
        str(
            await page.evaluate("() => document.getElementById('autojob-unknown-done').disabled")
        ).lower()
        == "true"
    )
    await page.evaluate("""() => {
      const a=document.getElementById('a'); a.focus(); a.value='Partial';
      a.dispatchEvent(new Event('input',{bubbles:true}));
    }""")
    assert not (await read(page))["done"]
    await page.evaluate("""() => {
      document.getElementById('a').value='';
      document.getElementById('autojob-unknown-done').click();
    }""")
    assert (await read(page))["value"] == ""


async def test_marker_loss_checkbox_group_requires_done_and_reads_all_ticks(page):
    await page.evaluate("""() => document.getElementById('red')
        .setAttribute('data-autojob-fill','lost-red')""")
    await page.evaluate(_WATCH_FORM_ANSWER_JS, ["lost-red", "lost-blue"])
    await page.evaluate(_SHOW_UNKNOWN_JS, "Tools", "")
    await page.evaluate("() => document.getElementById('red').click()")
    first = await read(page, ["lost-red", "lost-blue"], "tools", "Tools", ["Red", "Blue"])
    assert first["value"] == "Red" and not first["done"]
    await page.evaluate("() => document.getElementById('blue').click()")
    await read(page, ["lost-red", "lost-blue"], "tools", "Tools", ["Red", "Blue"])
    await page.evaluate("() => document.getElementById('autojob-unknown-done').click()")
    final = await read(page, ["lost-red", "lost-blue"], "tools", "Tools", ["Red", "Blue"])
    assert final["value"] == "Red, Blue" and final["done"]


async def test_prefilled_text_is_only_adopted_when_not_being_edited(page):
    await page.evaluate("() => document.getElementById('a').value='Complete answer'")
    await page.evaluate(_WATCH_FORM_ANSWER_JS, ["a"])
    assert (await read(page))["done"]
    await page.evaluate("() => document.getElementById('a').focus()")
    assert not (await read(page))["done"]
    await page.evaluate("() => document.getElementById('a').blur()")
    assert (await read(page))["done"]


@pytest.mark.parametrize("kind", ["select", "radio", "checkbox"])
async def test_single_choices_commit_without_done(page, kind):
    await page.evaluate(
        """(kind) => {
      const a=document.getElementById('a');
      if(kind==='select') a.outerHTML='<select id="a" data-autojob-fill="a">'
        + '<option value="">Select an option</option><option>Yes</option></select>';
          else { a.type=kind; a.parentElement.firstChild.textContent='Yes'; }
    }""",
        kind,
    )
    await page.evaluate(_WATCH_FORM_ANSWER_JS, ["a"])
    if kind == "select":
        assert (await read(page))["value"] == ""
        await page.evaluate("""() => {
          const a=document.getElementById('a'); a.focus(); a.value='Yes';
          a.dispatchEvent(new Event('change',{bubbles:true}));
        }""")
    else:
        await page.evaluate("() => document.getElementById('a').click()")
    result = await read(page)
    assert result["value"] and result["done"]
