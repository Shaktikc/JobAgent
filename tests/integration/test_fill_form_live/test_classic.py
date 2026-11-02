"""Live form classic checks; see common.py for setup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.configuration import Settings
from src.tools import browser as browser_tools

pytest.importorskip("browser_use")

from .common import _ANSWERS, _RESUME_NAME, _settings, _store_chooser
from .common import pytestmark as pytestmark

_FORM_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Easy Apply</title></head>
<body>
<div class="artdeco-modal jobs-easy-apply-modal" role="dialog">
  <div class="artdeco-modal__content">
    <section data-step="1">
      <div class="fb-dash-form-element">
        <label for="phone">Phone number*</label>
        <input id="phone" name="phone" type="text" required>
      </div>
      <div class="fb-dash-form-element">
        <label for="city">City*</label>
        <input id="city" name="city" type="text">
      </div>
      <fieldset class="jobs-easy-apply-form-element">
        <legend>Are you authorised to work in Australia?*</legend>
        <label for="auth-yes">Yes</label>
        <input id="auth-yes" name="work_auth" type="radio" value="Yes">
        <label for="auth-no">No</label>
        <input id="auth-no" name="work_auth" type="radio" value="No">
      </fieldset>
      <fieldset class="jobs-easy-apply-form-element">
        <legend>Select a resume</legend>
        <label for="resume-listed">__LISTED_RESUME__</label>
        <input id="resume-listed" name="resume" type="radio" value="listed">
      </fieldset>
      <input id="resume-file" name="resume_file" type="file">
    </section>
    <section data-step="2" style="display:none">
      <div class="fb-dash-form-element">
        <label for="experience">Years of experience*</label>
        <select id="experience" name="experience">
          <option value="">Choose</option>
          <option value="3">3</option>
          <option value="5">5</option>
        </select>
      </div>
    </section>
  </div>
  <footer class="artdeco-modal__actionbar">
    <button type="button" id="next-btn">Next</button>
    <button type="button" id="submit-btn" style="display:none">Submit application</button>
  </footer>
</div>
<script>
  window.__step = 1;
  window.__submitted = false;
  var step1 = document.querySelector('section[data-step="1"]');
  var step2 = document.querySelector('section[data-step="2"]');
  var next = document.getElementById('next-btn');
  var submit = document.getElementById('submit-btn');
  next.addEventListener('click', function () {
    step1.style.display = 'none';
    step2.style.display = 'block';
    next.style.display = 'none';
    submit.style.display = 'inline-block';
    window.__step = 2;
  });
  submit.addEventListener('click', function () { window.__submitted = true; });
</script>
</body></html>
"""


# A form whose "Review" step renders asynchronously (LinkedIn can take a moment).
# The walk must poll for the new step instead of stopping on the first read.
_DELAYED_REVIEW_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Easy Apply</title></head>
<body>
<div class="jobs-easy-apply-modal artdeco-modal" role="dialog">
  <h3>Apply to Delayed Co</h3>
  <div class="artdeco-modal__content">
    <section data-step="1">
      <div class="jobs-easy-apply-form-section__grouping">
        <span class="fb-form-element-label">Are you authorised to work here?</span>
        <div class="fb-form-element-wrapper">
          <div class="fb-dash-form-element" role="radio" aria-checked="true"><span>Yes</span></div>
          <div class="fb-dash-form-element" role="radio" aria-checked="false"><span>No</span></div>
        </div>
      </div>
    </section>
    <section data-step="2" style="display:none"><p>Review your application.</p></section>
  </div>
  <footer class="artdeco-modal__actionbar">
    <button id="review-btn">Review</button>
    <button id="submit-btn" style="display:none">Submit application</button>
  </footer>
</div>
<script>
  document.getElementById('review-btn').addEventListener('click', function () {
    setTimeout(function () {
      document.querySelector('section[data-step="1"]').style.display = 'none';
      document.querySelector('section[data-step="2"]').style.display = 'block';
      document.getElementById('review-btn').style.display = 'none';
      document.getElementById('submit-btn').style.display = 'inline-block';
      document.querySelector('h3').textContent = 'Review your application';
    }, 1500);
  });
  document.getElementById('submit-btn').addEventListener('click', function () {
    window.__submitted = true;
  });
</script>
</body></html>
"""

_READ_STATE_JS = """() => JSON.stringify({
  submitted: window.__submitted === true,
  step: window.__step,
  phone_value: document.getElementById('phone').value,
  auth_checked: document.getElementById('auth-yes').checked,
  experience_value: document.getElementById('experience').value,
  listed_checked: document.getElementById('resume-listed').checked,
  files: (() => {
    const f = document.getElementById('resume-file');
    return f && f.files ? f.files.length : -1;
  })(),
  file_name: (() => {
    const f = document.getElementById('resume-file');
    return f && f.files && f.files[0] ? f.files[0].name : '';
  })()
})"""


async def _run_task4_on_fixture(
    tmp_path: Path,
    settings: Settings,
    *,
    listed_resume: str,
    chosen_resume_name: str,
) -> tuple[object, dict]:
    """Drive the real Task 4 code over the fixture; return (outcome, page facts)."""
    resume_file = tmp_path / "resumes" / chosen_resume_name
    resume_file.parent.mkdir(parents=True, exist_ok=True)
    resume_file.write_text("Senior Python engineer", encoding="utf-8")

    form_file = tmp_path / "easy_apply.html"
    form_file.write_text(_FORM_HTML.replace("__LISTED_RESUME__", listed_resume), encoding="utf-8")

    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(form_file.as_uri())
        await browser_tools._wait_for_load(page, 10)

        answers = dict(_ANSWERS)
        outcome = await browser_tools._task4_on_page(
            page,
            browser,
            str(resume_file),
            answers,
            settings,
            lambda _m: None,
            chooser=_store_chooser(answers),
        )

        # Capture page-observed facts before the session is closed.
        observed = json.loads(await page.evaluate(_READ_STATE_JS))
        return outcome, observed
    finally:
        await browser.kill()

async def test_task4_waits_for_an_async_review_step(tmp_path: Path) -> None:
    """Clicking Review and reading instantly must not stop before it renders."""
    form_file = tmp_path / "delayed_review.html"
    form_file.write_text(_DELAYED_REVIEW_HTML, encoding="utf-8")
    settings = _settings(tmp_path)

    browser = browser_tools.build_browser(settings)
    try:
        await browser.start()
        page = await browser.new_page()
        await page.goto(form_file.as_uri())
        await browser_tools._wait_for_load(page, 10)
        outcome = await browser_tools._task4_on_page(
            page, browser, None, {}, settings, lambda _m: None
        )
    finally:
        await browser.kill()

    assert outcome.steps_advanced == 1
    assert outcome.reached_terminal_step is True
    assert outcome.submitted is False
    assert "form did not advance" not in outcome.notes


async def test_task4_fills_form_and_prefers_listed_resume(tmp_path: Path) -> None:
    """Known fields are filled, the listed resume is selected, Submit is untouched."""
    outcome, observed = await _run_task4_on_fixture(
        tmp_path,
        _settings(tmp_path),
        listed_resume=_RESUME_NAME,
        chosen_resume_name=_RESUME_NAME,
    )

    # The form was found and its fields enumerated.
    assert outcome.form_open is True
    assert outcome.fields_enumerated >= 5

    # Every known field was filled; the unknown "City" was left for Task 5.
    assert outcome.known_fields >= 3
    assert outcome.filled_fields == outcome.known_fields
    assert "City*" in outcome.unknown_fields
    assert observed["phone_value"] == "+61 400 000 000"
    assert observed["auth_checked"] is True
    assert observed["experience_value"] == "5"

    # The resume already listed on the form was selected, not uploaded.
    assert outcome.resume_attached is True
    assert outcome.resume_selection == "listed"
    assert outcome.resume_listed_name == _RESUME_NAME
    assert outcome.upload_attempted is False
    assert observed["listed_checked"] is True
    assert observed["files"] in (0, -1)

    # The form advanced one step and the application was never submitted.
    assert outcome.steps_advanced == 1
    assert observed["step"] == 2
    assert outcome.submitted is False
    assert observed["submitted"] is False


async def test_task4_uploads_resume_when_not_listed(tmp_path: Path) -> None:
    """When nothing listed matches, the chosen resume is uploaded over CDP."""
    outcome, observed = await _run_task4_on_fixture(
        tmp_path,
        _settings(tmp_path),
        listed_resume="Some_Other_Resume.pdf",
        chosen_resume_name=_RESUME_NAME,
    )

    assert outcome.resume_attached is True
    assert outcome.resume_selection == "uploaded"
    assert outcome.upload_attempted is True
    # The file actually arrived on the form's file input.
    assert observed["files"] == 1
    assert observed["file_name"] == _RESUME_NAME
    assert outcome.submitted is False
    assert observed["submitted"] is False
