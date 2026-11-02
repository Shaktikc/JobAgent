"""Task 21 DOM regressions in real Chromium (AUTOJOB_REQUIRED_LIVE=1).

LinkedIn verification is recorded separately; these fixtures exercise markup
variants and misleading metadata without sending an application.
"""

import os

import pytest
import pytest_asyncio

from src.configuration import SessionSettings, Settings
from src.tools.browser import build_browser
from src.tools.linkedin_easy_apply_fill.form_queries import read_form

pytest.importorskip("browser_use")
pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_REQUIRED_LIVE"), reason="set AUTOJOB_REQUIRED_LIVE=1"
)


@pytest_asyncio.fixture
async def page(tmp_path):
    browser = build_browser(Settings(data_dir=tmp_path, session=SessionSettings(headless=True)))
    await browser.start()
    try:
        yield await browser.new_page()
    finally:
        await browser.kill()


async def show(page, tmp_path, body):
    fixture = tmp_path / "required_labels.html"
    fixture.write_text(
        '<dialog open><h2>Apply to Example</h2>' + body
        + '<button type="button">Submit application</button></dialog>', encoding="utf-8"
    )
    await page.goto(fixture.as_uri())
    opened, _, fields, _ = await read_form(page)
    assert opened
    return fields


async def test_classic_labels_override_metadata_and_aria_text(page, tmp_path):
    fields = await show(page, tmp_path, """
      <section class="jobs-easy-apply-form-section" aria-required="true">
        <div><label for="needed">Availability <span>*</span></label>
          <input id="needed" name="needed" aria-label="Availability"></div>
        <div><label for="note">Additional details</label>
          <textarea id="note" name="note" required aria-required="true"></textarea></div>
        <div><label for="choice">Preferred team</label>
          <select id="choice" name="choice" required><option>Existing</option></select></div>
        <div><label for="hidden">Other details <span hidden>*</span></label>
          <input id="hidden" name="hidden" required></div>
        <div><label for="invisible">More details <span style="visibility:hidden">*</span></label>
          <input id="invisible" name="invisible" required></div>
        <div class="fb-form-element-wrapper"><span class="fb-form-element-label">Phone *</span>
          <div><input name="phone"></div></div>
      </section>
    """)
    assert [(f["question"], f["required"]) for f in fields] == [
        ("Availability *", True), ("Additional details", False),
        ("Preferred team", False), ("Other details", False), ("More details", False),
        ("Phone *", True),
    ]


@pytest.mark.parametrize("kind", ["radio", "checkbox"])
@pytest.mark.parametrize("helper", ["", "<p>This question is voluntary.</p>"])
async def test_sdui_own_group_heading_wins_over_error_ids_and_option_stars(
    page, tmp_path, kind, helper
):
    fields = await show(page, tmp_path, f"""
      <section role="group" aria-required="true">
        <h3>Additional questions *</h3>
        <div><p>Required question *</p>
          <fieldset aria-describedby="error-message-required">
            <input type="{kind}" name="needed" aria-label="Required question"><label>Yes</label>
            <input type="{kind}" name="needed" aria-label="Required question"><label>No</label>
          </fieldset></div>
        <div><p>Unstarred question</p>{helper}
          <fieldset aria-required="true" aria-describedby="error-message-optional">
            <input type="{kind}" name="optional" required aria-label="Unstarred question">
            <label>Option with its own *</label>
            <input type="{kind}" name="optional" aria-label="Unstarred question"><label>No</label>
          </fieldset></div>
      </section>
    """)
    assert [(f["question"], f["required"]) for f in fields] == [
        ("Required question *", True), ("Required question *", True),
        ("Unstarred question", False), ("Unstarred question", False),
    ]


async def test_sibling_groups_do_not_share_headings_or_option_asterisks(page, tmp_path):
    fields = await show(page, tmp_path, """
      <section class="jobs-easy-apply-form-section">
        <fieldset><legend>First question *</legend>
          <label><input type="radio" name="first">Yes</label></fieldset>
        <fieldset aria-required="true"><legend>Second question</legend>
          <label><input type="radio" name="second" required>Option *</label></fieldset>
        <p>Third question</p><fieldset aria-describedby="error-message-third">
          <label><input type="checkbox" name="third">Select *</label></fieldset>
      </section>
    """)
    assert [(f["question"], f["required"]) for f in fields] == [
        ("First question *", True), ("Second question", False), ("Third question", False),
    ]


async def test_visible_group_label_references_and_missing_labels(page, tmp_path):
    fields = await show(page, tmp_path, """
      <p id="required">Skills <span aria-hidden="true">*</span></p>
      <div role="group" aria-label="Skills" aria-labelledby="required">
        <label><input type="checkbox" name="skills">Python</label></div>
      <fieldset aria-label="Other skills *" required>
        <label><input type="checkbox" name="unlabelled">Python *</label></fieldset>
      <input name="no-visible-label" aria-label="Invisible question *" required>
    """)
    assert [(f["question"], f["required"]) for f in fields] == [
        ("Skills *", True), ("", False), ("", False),
    ]


async def test_internal_heading_and_unlabelled_options_never_borrow_markers(page, tmp_path):
    fields = await show(page, tmp_path, """
      <fieldset><p>Internal heading *</p>
        <label><input type="checkbox">Yes</label></fieldset>
      <div><label><input type="radio" name="radio">Option *</label>
        <label><input type="radio" name="radio">Other</label></div>
      <div><label><input type="checkbox" name="boxes">Option *</label>
        <label><input type="checkbox" name="boxes">Other</label></div>
      <div id="section"><p>Section *</p><input name="elsewhere"></div>
      <input name="bad-reference" aria-labelledby="section">
    """)
    assert [(f["question"], f["required"]) for f in fields] == [
        ("Internal heading *", True), ("", False), ("", False),
        ("", False), ("", False), ("Section *", True), ("", False),
    ]
