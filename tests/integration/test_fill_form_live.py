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
        <label for="city">City</label>
        <input id="city" name="city" type="text">
      </div>
      <fieldset class="jobs-easy-apply-form-element">
        <legend>Are you authorised to work in Australia?</legend>
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
        <label for="experience">Years of experience</label>
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
        <span class="fb-form-element-label">Are you authorised to work in Australia?</span>
        <div class="fb-form-element-wrapper">
          <div class="fb-dash-form-element" role="radio" aria-checked="false" data-option="Yes"><span>Yes</span></div>
          <div class="fb-dash-form-element" role="radio" aria-checked="false" data-option="No"><span>No</span></div>
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
    <button aria-label="Submit application" id="submit-btn" style="display:none">Submit application</button>
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
    assert "City" in outcome.unknown_fields
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
