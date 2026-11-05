"""Browser regressions for missing answers and question-owned feedback."""

import os

import pytest

from src.configuration import SessionSettings, Settings
from src.tools.browser import build_browser
from src.tools.linkedin_easy_apply_fill.form_queries import read_form
from src.tools.linkedin_validation.detection import read_rejections

pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_FILL_LIVE"), reason="set AUTOJOB_FILL_LIVE=1"
)


@pytest.mark.parametrize("message", [
    "This field is required", "Required", "Please select an option",
])
async def test_deep_group_feedback_belongs_only_to_its_question(tmp_path, message):
    settings = Settings(data_dir=tmp_path / "data", session=SessionSettings(headless=True))
    browser = build_browser(settings)
    await browser.start()
    try:
        fixture = tmp_path / "required.html"
        fixture.write_text(
            f'''<dialog open><h2>Apply to Example</h2>
            <fieldset><legend>Daily tools*</legend>
              <div><div><div><div><div><div>
                <label><input type="radio" name="tools">Yes</label>
                <label><input type="radio" name="tools">No</label>
              </div></div></div></div></div></div>
              <p role="alert">{message}</p>
            </fieldset>
            <fieldset><legend>Other question*</legend>
              <label><input type="radio" name="other" value="yes">Yes</label>
              <label><input type="radio" name="other" value="no">No</label>
              <p hidden role="alert">This field is required</p>
            </fieldset><button>Review</button></dialog>''', encoding="utf-8",
        )
        page = await browser.new_page(fixture.as_uri())
        _, _, fields, _ = await read_form(page)
        issues = await read_rejections(page, fields)
        assert issues
        assert {issue["question"] for issue in issues} == {"Daily tools*"}
        assert all(issue["message"] == message for issue in issues)
    finally:
        await browser.kill()


async def test_error_reference_cannot_borrow_another_questions_feedback(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", session=SessionSettings(headless=True))
    browser = build_browser(settings)
    await browser.start()
    try:
        fixture = tmp_path / "references.html"
        fixture.write_text('''<dialog open><h2>Apply to Example</h2>
          <div><label for="one">First*</label><input id="one" aria-describedby="other-error"></div>
          <div><label for="two">Other*</label><input id="two">
            <p role="alert" id="other-error">This field is required</p></div>
          <button>Review</button></dialog>''', encoding="utf-8")
        page = await browser.new_page(fixture.as_uri())
        fields = (await read_form(page))[2]
        issues = await read_rejections(page, fields)
        assert {issue["question"] for issue in issues} == {"Other*"}
    finally:
        await browser.kill()
