"""Live form hidden dialog checks; see common.py for setup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tools import browser as browser_tools

pytest.importorskip("browser_use")

from .common import _RESUME_NAME, _settings, _store_chooser
from .common import pytestmark as pytestmark

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
        <label for="phone">Phone number*</label>
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
