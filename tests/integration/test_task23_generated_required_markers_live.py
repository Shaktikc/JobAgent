"""Visible CSS-generated asterisks must reach Task 10; hidden markers must not."""

import json
import os

import pytest

from src.configuration import SessionSettings, Settings
from src.tools.browser import build_browser
from src.tools.linkedin_easy_apply_fill.field_filling import _fill_step
from src.tools.linkedin_easy_apply_fill.form_queries import read_form
from src.tools.llm_answers import QuestionDecision

pytest.importorskip("browser_use")
pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_REQUIRED_LIVE"), reason="set AUTOJOB_REQUIRED_LIVE=1",
)


async def test_generated_markers_preserve_required_questions_and_optional_neighbors(tmp_path):
    fixture = tmp_path / "generated_markers.html"
    fixture.write_text("""<!doctype html><style>
      .star::after {content: "*";}
      .before::before {content: "*";}
      .hidden::after {display: none;}
      .invisible::after {visibility: hidden;}
      .transparent::after {opacity: 0;}
    </style><dialog open><h2>Apply to Example</h2>
      <div><label for="years" class="star">
        <span style="display:contents">Years of Python experience</span></label>
        <input id="years" required></div>
      <div><label for="notice">Notice period<span class="star"></span></label>
        <textarea id="notice" required></textarea></div>
      <div><label for="country" class="before">Country</label>
        <select id="country"><option value="">Select an option</option>
        <option value="AU">Australia</option></select></div>
      <div><p class="star">Work authorization</p><fieldset>
        <label><input type="radio" name="authorized" value="Yes">Yes</label>
        <label><input type="radio" name="authorized" value="No">No</label>
      </fieldset></div>
      <div><label for="optional">Additional details</label>
        <input id="optional" required value="Keep"></div>
      <div><label for="hidden" class="star hidden">Hidden marker</label>
        <input id="hidden" required value="Keep"></div>
      <div><label for="invisible" class="star invisible">Invisible marker</label>
        <input id="invisible" required value="Keep"></div>
      <div><label for="transparent" class="star transparent">Transparent marker</label>
        <input id="transparent" required value="Keep"></div>
      <div><p>Optional with helper</p><input id="helper" value="Keep">
        <p class="star">Trailing helper</p></div>
      <button>Submit application</button>
    </dialog>""", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", session=SessionSettings(headless=True))
    browser = build_browser(settings)
    await browser.start()
    try:
        page = await browser.new_page(fixture.as_uri())
        opened, _, fields, _ = await read_form(page)
        assert opened
        required = [field for field in fields if field["required"]]
        assert len(required) == 5  # three text/select controls and two radio options
        assert all("*" in field["question"] for field in required)
        calls = []

        async def choose(question, kind, options):
            calls.append(question)
            answer = next(value for key, value in {
                "Years of Python": "5", "Notice period": "2 weeks",
                "Country": "Australia", "Work authorization": "Yes",
            }.items() if key in question)
            return QuestionDecision(question=question, answer=answer)

        known, filled, unknown, _ = await _fill_step(
            page, fields, {}, settings, chooser=choose,
        )
        assert (known, filled, unknown) == (4, 4, [])
        assert len(calls) == 4
        values = json.loads(await page.evaluate("""() => JSON.stringify(
          ['years','notice','country','optional','hidden','invisible','transparent','helper']
            .map(id => document.getElementById(id).value))"""))
        assert values == ["5", "2 weeks", "AU", "Keep", "Keep", "Keep", "Keep", "Keep"]
    finally:
        await browser.kill()
