"""Opt-in live-browser test for Task 4: fill the Easy Apply form, never submit.

Unlike ``test_login_search_live`` this needs no LinkedIn account, no login, and
no network. It serves a self-contained two-step Easy Apply fixture from a local
file and drives the **real** Task 4 code path (:func:`_task4_on_page`) in a real
Chromium window built by :func:`build_browser`.

Enable it (the ``browser`` extra must be installed)::

    uv sync --extra browser
    uvx playwright install chromium
    $env:AUTOJOB_FILL_LIVE="1"
    uv run pytest tests/integration/test_fill_form_live.py -s

Watch it in **slow mode** so each visible step pauses::

    $env:AUTOJOB_FILL_LIVE="1"
    $env:AUTOJOB_SESSION_HEADLESS="false"     # show the window
    $env:AUTOJOB_FILL_TEST_STEP_DELAY="2"     # seconds between visible steps
    uv run pytest tests/integration/test_fill_form_live.py -s

Skipped by default (no browser extra / flag unset) so the unit suite stays fast.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task5Outcome
from src.tools import browser as browser_tools
from src.tools.answers import normalize_question
from src.tools.llm_answers import QuestionDecision
from src.tools.self_healing.fingerprint import fill_failure_reason

pytest.importorskip("browser_use")


def _store_chooser(answers: dict):
    """Stand in for the Task 4.1 LLM so the live tests never hit the network."""

    async def choose(question: str, field_type: str, options: list[str]) -> QuestionDecision:
        key = normalize_question(question)
        for stored_key, value in answers.items():
            if stored_key == key or (stored_key and stored_key in key):
                return QuestionDecision(
                    question=question,
                    category="test",
                    answer=value,
                    matched_key=stored_key,
                    rationale="test chooser",
                )
        return QuestionDecision(question=question)

    return choose

_RESUME_NAME = "ShaktiKC_Resume_python_Node_Senior.txt"

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("AUTOJOB_FILL_LIVE"),
        reason="set AUTOJOB_FILL_LIVE=1 to run the live Task 4 browser test",
    ),
    # browser-use's Chromium subprocess leaves a ProactorEventLoop pipe transport
    # for GC after the session is killed; on Windows it is torn down after the
    # loop closes, raising a harmless ResourceWarning. Scope it here so it cannot
    # mask unrelated warnings elsewhere.
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]


# A LinkedIn-shaped two-step Easy Apply modal. ``__LISTED_RESUME__`` is replaced
# by the resume name the form pretends is already on file. Step 1 holds a text
# field, an unknown text field, a required Yes/No radio group, the resume list,
# and a file input. Clicking "Next" reveals step 2 with a select and the only
# "Submit application" button (hidden until the last step, so the agent must
# advance without ever being able to submit).
_FORM_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Easy Apply</title></head>
<body>
<div class="artdeco-modal jobs-easy-apply-modal" role="dialog">
  <div class="artdeco-modal__content">
    <section data-step="1">
      <div class="fb-dash-form-element">
        <label for="phone">Phone number</label>
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


def _settings(tmp_path: Path, *, ask_human: bool = False) -> Settings:
    """Browser settings; slow motion + visibility are env-controlled.

    Task 5's browser prompt is off unless a test supplies a (simulated) human.
    """
    delay = float(os.environ.get("AUTOJOB_FILL_TEST_STEP_DELAY", "0"))
    headless = os.environ.get("AUTOJOB_SESSION_HEADLESS", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    return Settings(
        session=SessionSettings(
            headless=headless,
            step_delay_seconds=delay,
            post_click_wait_seconds=0.0,
            ask_human=ask_human,
            ask_timeout_seconds=30.0,
            ask_poll_seconds=0.1,
        ),
        data_dir=tmp_path / "data",
    )


_ANSWERS = {
    "phone number": "+61 400 000 000",
    "are you authorised to work in australia": "Yes",
    "years of experience": "5",
}

# Read the fixture's resulting state as one JSON payload (browser-use returns
# ``str(value)`` for ``page.evaluate``, so JSON.stringify keeps the types intact).
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


# A LinkedIn-shaped Easy Apply modal that mirrors the 2026 markup: screening
# questions render as styled ``[role="radio"]`` divs inside
# ``.jobs-easy-apply-form-section__grouping`` (question text in
# ``.fb-form-element-label``), and the resume chooser is a ``<select>``. The
# older ``.fb-dash-form-element`` + ``label[for]`` helpers must still read these.
_FORM_HTML_2026 = """<!doctype html>
<html><head><meta charset="utf-8"><title>Easy Apply</title></head>
<body>
<div class="jobs-easy-apply-modal artdeco-modal" role="dialog">
  <div class="artdeco-modal__content">
    <section class="jobs-easy-apply-form-section" data-step="1">
      <h3>Application</h3>
      <div class="jobs-easy-apply-form-section__grouping">
        <label class="fb-form-element-label" for="mobile-phone">Mobile phone number</label>
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


# A page that also carries an unrelated, hidden dialog *earlier in the DOM* than
# the real Easy Apply modal. A naive ``document.querySelector`` picks the hidden
# one and fills nothing, so Task 4 must select the visible Easy Apply modal.
_FORM_HTML_WITH_HIDDEN_DIALOG = """<!doctype html>
<html><head><meta charset="utf-8"><title>Easy Apply</title></head>
<body>
<div class="artdeco-modal" role="dialog" style="display:none">
  <div class="artdeco-modal__content">
    <h3>Save this job</h3>
    <input id="note" name="note" type="text">
  </div>
</div>
<div class="artdeco-modal jobs-easy-apply-modal" role="dialog">
  <div class="artdeco-modal__content">
    <section data-step="1">
      <div class="fb-dash-form-element">
        <label for="phone">Phone number</label>
        <input id="phone" name="phone" type="text" required>
      </div>
    </section>
  </div>
  <footer class="artdeco-modal__actionbar">
    <button type="button" id="submit-btn">Submit application</button>
  </footer>
</div>
</body></html>
"""

_READ_HIDDEN_DIALOG_STATE_JS = """() => JSON.stringify({
  phone_value: document.getElementById('phone').value
})"""


async def test_task4_ignores_a_hidden_dialog_before_the_easy_apply_modal(
    tmp_path: Path,
) -> None:
    """An unrelated hidden .artdeco-modal earlier in the DOM must not shadow the form.

    Regression: the modal lookup used the *first* matching element, so a hidden
    dialog (e.g. "Save this job") appearing before the Easy Apply modal made the
    fill walk enumerate zero fields and fill nothing.
    """
    resume_file = tmp_path / "resumes" / _RESUME_NAME
    resume_file.parent.mkdir(parents=True, exist_ok=True)
    resume_file.write_text("Senior Python engineer", encoding="utf-8")

    form_file = tmp_path / "easy_apply_hidden_dialog.html"
    form_file.write_text(_FORM_HTML_WITH_HIDDEN_DIALOG, encoding="utf-8")

    settings = _settings(tmp_path)
    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(form_file.as_uri())
        await browser_tools._wait_for_load(page, 10)

        answers = {"phone number": "+61 400 000 000"}
        outcome = await browser_tools._task4_on_page(
            page,
            browser,
            str(resume_file),
            answers,
            settings,
            lambda _m: None,
            chooser=_store_chooser(answers),
        )
        observed = json.loads(await page.evaluate(_READ_HIDDEN_DIALOG_STATE_JS))
    finally:
        await browser.kill()

    # The real (visible) Easy Apply modal was chosen, not the hidden dialog.
    assert outcome.form_open is True
    assert outcome.fields_enumerated >= 1
    assert observed["phone_value"] == "+61 400 000 000"
    assert outcome.submitted is False


# LinkedIn's AI/semantic job view renders Easy Apply as an **inline** full-page
# form with hashed CSS-in-JS classes (no artdeco/jobs-easy-apply-modal classes).
# It is identifiable only by its "Apply to <company>" heading and application
# controls, so Task 4 must find the form via the shared root finder.
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


# LinkedIn's newer SDUI Easy Apply uses a native <dialog> with hashed classes and
# no role/artdeco hooks. It renders the "Apply to <company>" heading first and the
# fields/footer a moment later; the page also carries an unrelated "Next" button,
# which the old ancestor-climb could mistake for the form (BUG-056).
_LATE_DIALOG_FORM_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Apply</title></head>
<body>
<button id="wrong-next" type="button">Next</button>
<dialog open class="l4jlpi l4jlph">
  <header><h2>Apply to Late Co</h2></header>
  <div id="dialog-body"></div>
  <footer id="dialog-footer"></footer>
</dialog>
<script>
  window.__wrong_next = false;
  window.__submitted = false;
  window.__step = 0;
  window.__city_committed = false;
  document.getElementById('wrong-next').addEventListener('click', function () {
    window.__wrong_next = true;
  });

  function renderSuggestions() {
    if (document.getElementById('city-options')) return;
    var wrap = document.getElementById('city-wrap');
    var box = document.createElement('div');
    box.id = 'city-options';
    box.setAttribute('role', 'listbox');
    ['Sydney, New South Wales, Australia',
     'North Sydney, New South Wales, Australia'].forEach(function (text) {
      var option = document.createElement('div');
      option.setAttribute('role', 'option');
      option.textContent = text;
      option.addEventListener('click', function () {
        var input = document.getElementById('city');
        input.value = text;
        input.setAttribute('data-committed', '1');
        window.__city_committed = true;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        box.remove();
        var status = document.getElementById('city-status');
        if (status) status.remove();
      });
      box.appendChild(option);
    });
    wrap.appendChild(box);
    var status = document.createElement('div');
    status.id = 'city-status';
    status.setAttribute('role', 'status');
    status.textContent = '2 suggestions available, use up and down arrow keys to navigate';
    wrap.appendChild(status);
  }

  function toggleSuggestions() {
    var box = document.getElementById('city-options');
    if (box) {
      box.remove();
      var status = document.getElementById('city-status');
      if (status) status.remove();
    } else {
      renderSuggestions();
    }
  }

  // The heading is already in the DOM; the real controls arrive after a pause.
  setTimeout(function () {
    document.getElementById('dialog-body').innerHTML =
      '<div><label for="phone">Mobile phone number*</label>' +
      '<input id="phone" name="phone" type="text" required></div>' +
      '<div id="city-wrap"><p>Location (city)*</p>' +
      '<input id="city" name="city" type="text" role="combobox"' +
      ' aria-autocomplete="list" aria-owns="city-options" required' +
      ' placeholder="Enter city or location"></div>';
    document.getElementById('city').addEventListener('input', function () {
      setTimeout(renderSuggestions, 100);
    });
    document.getElementById('dialog-footer').innerHTML =
      '<button id="next" type="button">Next</button>';
    window.__step = 1;
    document.getElementById('next').addEventListener('click', function () {
      var city = document.getElementById('city');
      if (city && city.value && city.getAttribute('data-committed') !== '1') {
        // An uncommitted typeahead keeps the form on this step and toggles the
        // suggestion list, which used to look like a new step (BUG-056).
        toggleSuggestions();
        return;
      }
      document.getElementById('dialog-body').innerHTML =
        '<p>Review your application.</p>';
      document.getElementById('dialog-footer').innerHTML =
        '<button id="submit" type="button">Submit application</button>';
      window.__step = 2;
      document.getElementById('submit').addEventListener('click', function () {
        window.__submitted = true;
      });
    });
  }, 800);
</script>
</body></html>
"""

_READ_LATE_DIALOG_JS = """() => JSON.stringify({
  step: window.__step,
  wrong_next: window.__wrong_next === true,
  submitted: window.__submitted === true,
  city_committed: window.__city_committed === true
})"""


async def test_task4_waits_for_a_sdui_dialog_to_render_its_fields(tmp_path: Path) -> None:
    """A native <dialog> heading-only shell is found and filled, not page-level.

    The heading renders before the controls, and the page has an unrelated "Next"
    button. The walk must use the dialog (never the page heading or the page's
    Next) and wait for the fields rather than treating the shell as terminal.
    """
    form_file = tmp_path / "late_dialog_apply.html"
    form_file.write_text(_LATE_DIALOG_FORM_HTML, encoding="utf-8")

    settings = _settings(tmp_path)
    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(form_file.as_uri())
        await browser_tools._wait_for_load(page, 10)

        answers = {
            "mobile phone number": "+61 400 000 000",
            "enter city or location": "Sydney, New South Wales, Australia",
        }
        outcome = await browser_tools._task4_on_page(
            page,
            browser,
            None,
            answers,
            settings,
            lambda _m: None,
            chooser=_store_chooser(answers),
        )
        observed = json.loads(await page.evaluate(_READ_LATE_DIALOG_JS))
    finally:
        await browser.kill()

    assert outcome.form_open is True
    assert outcome.fields_enumerated >= 2
    assert outcome.filled_fields >= 2
    assert outcome.steps_advanced == 1
    assert outcome.reached_terminal_step is True
    assert outcome.submitted is False
    # The page's unrelated Next was never clicked; the dialog's Next advanced it.
    assert observed["wrong_next"] is False
    assert observed["step"] == 2
    # The city combobox's matching suggestion was clicked, so Next accepted it.
    assert observed["city_committed"] is True


# The step identity must not change when a typeahead's suggestion list or its
# live "N suggestions available" status appears/disappears; otherwise a Next click
# that did not advance looks like progress and the walk loops on the same step.
_TRANSIENT_STEP_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Step</title></head>
<body>
<dialog open>
  <h2>Apply to Transient Co</h2>
  <p>1/2 pages</p>
  <label for="city">Location (city)*</label>
  <input id="city" role="combobox" aria-autocomplete="list" aria-owns="city-options">
  <div id="city-slot"></div>
  <footer><button type="button">Next</button></footer>
</dialog>
</body></html>
"""

_TOGGLE_SUGGESTIONS_JS = """() => {
  const slot = document.getElementById('city-slot');
  if (slot.childElementCount) {
    slot.innerHTML = '';
    return 'closed';
  }
  slot.innerHTML =
    '<div id="city-options" role="listbox">' +
    '<div role="option">Sydney, New South Wales, Australia</div>' +
    '<div role="option">North Sydney, New South Wales, Australia</div></div>' +
    '<div role="status">2 suggestions available, use up and down arrow keys to navigate</div>';
  return 'open';
}"""


async def test_step_identity_ignores_transient_typeahead_text(tmp_path: Path) -> None:
    """Opening/closing suggestions must not look like a new Easy Apply step."""
    form_file = tmp_path / "transient_step.html"
    form_file.write_text(_TRANSIENT_STEP_HTML, encoding="utf-8")

    settings = _settings(tmp_path)
    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(form_file.as_uri())
        await browser_tools._wait_for_load(page, 10)

        _opened, _title, _fields, before = await browser_tools.read_form(page)
        assert await page.evaluate(_TOGGLE_SUGGESTIONS_JS) == "open"
        _opened, _title, _fields, opened = await browser_tools.read_form(page)
        assert await page.evaluate(_TOGGLE_SUGGESTIONS_JS) == "closed"
        _opened, _title, _fields, closed = await browser_tools.read_form(page)
    finally:
        await browser.kill()

    assert before == opened == closed


# A one-step form with a single required, unknown question. The agent must pause
# on the Task 5 banner; the test plays the human, types an answer, and submits it.
_TASK5_FORM_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Task 5</title></head>
<body>
<div class="artdeco-modal jobs-easy-apply-modal" role="dialog">
  <div class="artdeco-modal__content">
    <div class="fb-dash-form-element">
      <label for="email">Email address</label>
      <select id="email" name="email" required>
        <option value="me@example.com" selected>me@example.com</option>
      </select>
    </div>
    <div class="fb-dash-form-element">
      <label for="notice">Notice period</label>
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
        assert human.answered_questions == ["Notice period"]
        stored = browser_tools.load_answers(settings.answers_file)
        assert stored["notice period"] == "4 weeks"
        assert "email address" not in stored
    finally:
        await browser.kill()


# A one-step form with a required, unknown screening question rendered the way
# LinkedIn renders it: as ``<div role="radio" aria-checked="...">`` (not a real
# input). Clicking sets ``aria-checked``; the agent must capture that click, which
# fires no ``input``/``change``.
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


# A one-step form whose modal sits above a full-screen overlay with a very high
# z-index — the shape that pushed the Task 5 banner behind the modal.
_BANNER_ON_TOP_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Task 5 on top</title></head>
<body>
<div id="overlay" style="position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,.5)"></div>
<div class="artdeco-modal jobs-easy-apply-modal" role="dialog"
     style="position:fixed;inset:60px;z-index:100000;background:#fff">
  <div class="artdeco-modal__content">
    <div class="fb-dash-form-element">
      <label for="notice">Notice period</label>
      <input id="notice" name="notice" type="text" required>
    </div>
  </div>
  <footer class="artdeco-modal__actionbar">
    <button type="button" id="submit-btn" style="display:none">Submit application</button>
  </footer>
</div>
</body></html>
"""

_BANNER_ON_TOP_JS = """() => {
  const box = document.getElementById('autojob-unknown');
  if (!box) return JSON.stringify({ present: false });
  const r = box.getBoundingClientRect();
  const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return JSON.stringify({ present: true, onTop: !!(el && (el === box || box.contains(el))) });
}"""

_READ_STATUS_JS = """() => {
  const s = document.getElementById('autojob-unknown-status');
  return s ? s.textContent : '';
}"""


async def test_task5_banner_sits_above_the_modal_and_confirms_saving(tmp_path: Path) -> None:
    """The banner renders above a high-z-index modal and confirms the save."""
    settings = _settings(tmp_path, ask_human=True)

    form_file = tmp_path / "banner_on_top.html"
    form_file.write_text(_BANNER_ON_TOP_HTML, encoding="utf-8")

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

        # The banner must paint above the modal overlay (top layer), not behind it.
        on_top = json.loads(await page.evaluate(_BANNER_ON_TOP_JS))
        assert on_top["onTop"] is True

        # Answering shows the saved confirmation before the banner closes.
        await page.evaluate(_ANSWER_IN_FORM_JS, "4 weeks")
        saved = False
        for _ in range(120):
            status = await page.evaluate(_READ_STATUS_JS)
            if status and "Saved" in status:
                saved = True
                break
            await asyncio.sleep(0.05)
        assert saved, "the banner never confirmed the answer was saved"

        await asyncio.wait_for(fill_task, timeout=30)
        assert human.answered == 1
    finally:
        await browser.kill()


# A radio group rendered the way the real LinkedIn form does it: visually-styled
# native inputs whose option text ("Yes"/"No") is a sibling span (not an associated
# label), inside a container whose label is the *question*.
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


# The exact shape LinkedIn uses (from the live page): a ``div[role=radio]`` whose
# aria-label is the *question*, wrapping a native input with an empty ``label[for]``
# and the option text in a nested ``<p>``. Clicking swaps in a fresh node (React),
# dropping our marker — so detection must fall back to the input's ``name``.
_LINKEDIN_ROLE_RADIO_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Task 5 LinkedIn radio</title></head>
<body>
<div class="artdeco-modal jobs-easy-apply-modal" role="dialog">
  <div class="artdeco-modal__content">
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


# The exact LinkedIn role=radio shape (a ``div[role=radio]`` whose aria-label is
# the question, wrapping a native input with the group ``name`` and the option
# text in a nested ``<p>``). ``window.__rerenderRadios`` replaces each marked
# wrapper with a clone that has dropped ``data-autojob-fill``, the way React
# re-renders the group away while the LLM is choosing an answer (BUG-057).
_STALE_ROLE_RADIO_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Task 4 stale radio</title></head>
<body>
<div class="artdeco-modal jobs-easy-apply-modal" role="dialog">
  <div class="artdeco-modal__content">
    <h3>Apply to Hays</h3>
    <div class="hcbwrap">
      <div role="radio" tabindex="0" aria-checked="false" data-option="Yes"
           aria-label="Have you implemented and integrated AI voice, conversational
                       AI or chatbot platforms into production environments?*">
        <div><div>
          <input id="_r_1j_" type="radio" name="radio-group-_r_1g_">
          <label for="_r_1j_"></label>
        </div><div><p>Yes</p></div></div>
      </div>
      <div role="radio" tabindex="0" aria-checked="false" data-option="No"
           aria-label="Have you implemented and integrated AI voice, conversational
                       AI or chatbot platforms into production environments?*">
        <div><div>
          <input id="_r_1i_" type="radio" name="radio-group-_r_1g_">
          <label for="_r_1i_"></label>
        </div><div><p>No</p></div></div>
      </div>
    </div>
  </div>
  <footer class="artdeco-modal__actionbar">
    <button type="button" id="submit-btn">Submit application</button>
  </footer>
</div>
<script>
  document.addEventListener('click', function (e) {
    const r = e.target.closest && e.target.closest('[role="radio"]');
    if (!r) return;
    const group = r.parentElement;
    group.querySelectorAll('[role="radio"]').forEach(function (x) {
      x.setAttribute('aria-checked', 'false');
      const i = x.querySelector('input');
      if (i) { i.checked = false; i.removeAttribute('checked'); }
    });
    r.setAttribute('aria-checked', 'true');
    const input = r.querySelector('input');
    if (input) { input.checked = true; input.setAttribute('checked', ''); }
  });
  window.__rerenderRadios = function () {
    document.querySelectorAll('[role="radio"]').forEach(function (r) {
      const clone = r.cloneNode(true);
      clone.removeAttribute('data-autojob-fill');
      r.replaceWith(clone);
    });
  };
</script>
</body></html>
"""


async def test_task4_llm_answered_radio_survives_a_stale_marker_live(tmp_path: Path) -> None:
    """BUG-057 live: an LLM-answered radio is still filled after the marker goes stale.

    The chooser re-renders the marked radio wrappers (dropping ``data-autojob-fill``)
    before returning the stored "Yes", exactly as React can while the model is
    thinking. The group's native ``name`` survives, so the fill must re-resolve it
    by name, click "Yes", and not stop as "required fields were not filled".
    """
    settings = _settings(tmp_path)

    form_file = tmp_path / "stale_radio.html"
    form_file.write_text(_STALE_ROLE_RADIO_HTML, encoding="utf-8")

    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(form_file.as_uri())
        await browser_tools._wait_for_load(page, 10)

        async def chooser(question: str, field_type: str, options: list[str]):
            # Simulate React re-rendering the marked wrapper away mid-decision.
            await page.evaluate("() => window.__rerenderRadios()")
            return QuestionDecision(
                question=question,
                category="experience",
                answer="Yes",
                matched_key="production ai",
                rationale="stored production experience",
            )

        outcome = await browser_tools._task4_on_page(
            page, browser, None, {}, settings, lambda _m: None, chooser=chooser
        )

        checked = await page.evaluate(
            "() => document.querySelector('[role=\"radio\"][data-option=\"Yes\"]')"
            ".getAttribute('aria-checked')"
        )

        assert outcome.filled_fields == 1
        assert outcome.reached_terminal_step is True
        assert outcome.submitted is False
        record = outcome.fields[0]
        assert record.filled is True
        assert record.error == ""
        assert record.answered_by == "llm"
        assert str(checked).lower() == "true"
        assert "required fields were not filled" not in fill_failure_reason(outcome)
    finally:
        await browser.kill()

