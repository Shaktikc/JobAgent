"""Live form sdui checks; see common.py for setup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.configuration import Settings
from src.tools import browser as browser_tools

pytest.importorskip("browser_use")

from .common import _ANSWERS, _RESUME_NAME, _settings, _store_chooser
from .common import pytestmark as pytestmark

_FORM_HTML_2026 = """<!doctype html>
<html><head><meta charset="utf-8"><title>Easy Apply</title></head>
<body>
<div class="jobs-easy-apply-modal artdeco-modal" role="dialog">
  <div class="artdeco-modal__content">
    <section class="jobs-easy-apply-form-section" data-step="1">
      <h3>Application</h3>
      <div class="jobs-easy-apply-form-section__grouping">
        <label class="fb-form-element-label" for="mobile-phone">Mobile phone number*</label>
        <div class="fb-form-element-wrapper">
          <input id="mobile-phone" name="mobile-phone" type="text" required>
        </div>
      </div>
      <div class="jobs-easy-apply-form-section__grouping">
        <span class="fb-form-element-label">Are you authorised to work in Australia?*</span>
        <div class="fb-form-element-wrapper">
          <div class="fb-dash-form-element" role="radio" aria-checked="false"
               data-option="Yes"><span>Yes</span></div>
          <div class="fb-dash-form-element" role="radio" aria-checked="false"
               data-option="No"><span>No</span></div>
        </div>
      </div>
      <div class="jobs-easy-apply-form-section__grouping">
        <label class="fb-form-element-label" for="resume-select">Select a resume</label>
        <div class="fb-form-element-wrapper">
          <select id="resume-select" name="resume-select">
            <option value="">Choose</option>
            <option value="1">__LISTED_RESUME__</option>
            <option value="2">Some_Other_Resume.pdf</option>
          </select>
        </div>
      </div>
    </section>
    <section data-step="2" style="display:none"></section>
  </div>
  <footer class="artdeco-modal__actionbar">
    <button aria-label="Continue to next step" id="next-btn">Next</button>
    <button aria-label="Submit application" id="submit-btn"
            style="display:none">Submit application</button>
  </footer>
</div>
<script>
  window.__step = 1;
  window.__submitted = false;
  window.__radio = '';
  var step1 = document.querySelector('section[data-step="1"]');
  var step2 = document.querySelector('section[data-step="2"]');
  var next = document.getElementById('next-btn');
  var submit = document.getElementById('submit-btn');
  document.querySelectorAll('[role="radio"]').forEach(function (r) {
    r.addEventListener('click', function () {
      document.querySelectorAll('[role="radio"]').forEach(function (x) {
        x.setAttribute('aria-checked', 'false');
      });
      r.setAttribute('aria-checked', 'true');
      window.__radio = r.getAttribute('data-option');
    });
  });
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

_READ_STATE_JS_2026 = """() => JSON.stringify({
  submitted: window.__submitted === true,
  step: window.__step,
  phone_value: document.getElementById('mobile-phone').value,
  selected_radio: window.__radio,
  resume_value: document.getElementById('resume-select').value
})"""


async def _run_task4_on_fixture_2026(
    tmp_path: Path,
    settings: Settings,
    *,
    listed_resume: str,
    chosen_resume_name: str,
    answers: dict | None = None,
) -> tuple[object, dict]:
    """Drive the real Task 4 code over the 2026-markup fixture."""
    resume_file = tmp_path / "resumes" / chosen_resume_name
    resume_file.parent.mkdir(parents=True, exist_ok=True)
    resume_file.write_text("Senior Python engineer", encoding="utf-8")

    form_file = tmp_path / "easy_apply_2026.html"
    form_file.write_text(
        _FORM_HTML_2026.replace("__LISTED_RESUME__", listed_resume), encoding="utf-8"
    )

    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(form_file.as_uri())
        await browser_tools._wait_for_load(page, 10)

        answers = dict(answers or _ANSWERS)
        outcome = await browser_tools._task4_on_page(
            page,
            browser,
            str(resume_file),
            answers,
            settings,
            lambda _m: None,
            chooser=_store_chooser(answers),
        )
        observed = json.loads(await page.evaluate(_READ_STATE_JS_2026))
        return outcome, observed
    finally:
        await browser.kill()


async def test_task4_autofills_screening_questions_in_new_linkedin_markup(
    tmp_path: Path,
) -> None:
    """Stored answers fill text fields AND role=radio screening questions."""
    outcome, observed = await _run_task4_on_fixture_2026(
        tmp_path,
        _settings(tmp_path),
        listed_resume=_RESUME_NAME,
        chosen_resume_name=_RESUME_NAME,
        answers={**_ANSWERS, "mobile phone number": "+61 400 000 000"},
    )

    assert outcome.form_open is True
    # The screening question's text was extracted (not a bare marker), so the
    # stored "Yes" answer applies to the radio group.
    assert outcome.known_fields >= 2
    assert outcome.filled_fields == outcome.known_fields
    assert "Are you authorised to work in Australia?" not in outcome.unknown_fields
    assert observed["phone_value"] == "+61 400 000 000"
    assert observed["selected_radio"] == "Yes"

    # The listed resume was selected from the <select>, not uploaded.
    assert outcome.resume_attached is True
    assert outcome.resume_selection == "listed"
    assert outcome.upload_attempted is False
    assert observed["resume_value"] == "1"

    assert outcome.steps_advanced == 1
    assert observed["step"] == 2
    assert outcome.submitted is False
    assert observed["submitted"] is False

_INLINE_FORM_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Apply</title></head>
<body>
<div class="fmwrap">
  <h2>Apply to Acme</h2>
  <div class="fmrow">
    <label for="email">Email address*</label>
    <select id="email" name="email">
      <option value="me@example.com" selected>me@example.com</option>
    </select>
  </div>
  <div class="fmrow">
    <label for="phone">Mobile phone number*</label>
    <input id="phone" name="phone" type="tel">
  </div>
  <input id="resume-file" name="resume" type="file">
  <footer><button type="button" id="submit">Submit application</button></footer>
</div>
</body></html>
"""

_READ_INLINE_FORM_JS = """() => JSON.stringify({
  phone_value: document.getElementById('phone').value,
  email_value: document.getElementById('email').value,
  files: (() => {
    const f = document.getElementById('resume-file');
    return f && f.files ? f.files.length : -1;
  })()
})"""


async def test_task4_fills_inline_hashed_class_form(tmp_path: Path) -> None:
    """The inline full-page form (hashed classes, no modal) is found and filled."""
    resume_file = tmp_path / "resumes" / _RESUME_NAME
    resume_file.parent.mkdir(parents=True, exist_ok=True)
    resume_file.write_text("Senior Python engineer", encoding="utf-8")

    form_file = tmp_path / "inline_apply.html"
    form_file.write_text(_INLINE_FORM_HTML, encoding="utf-8")

    settings = _settings(tmp_path)
    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(form_file.as_uri())
        await browser_tools._wait_for_load(page, 10)

        answers = {"mobile phone number": "+61 400 000 000"}
        outcome = await browser_tools._task4_on_page(
            page,
            browser,
            str(resume_file),
            answers,
            settings,
            lambda _m: None,
            chooser=_store_chooser(answers),
        )
        observed = json.loads(await page.evaluate(_READ_INLINE_FORM_JS))
    finally:
        await browser.kill()

    assert outcome.form_open is True
    # The pre-filled email select is left alone; the phone is filled from the store.
    assert observed["email_value"] == "me@example.com"
    assert observed["phone_value"] == "+61 400 000 000"
    assert outcome.filled_fields >= 1
    assert outcome.resume_attached is True
    assert observed["files"] == 1
    assert outcome.submitted is False
