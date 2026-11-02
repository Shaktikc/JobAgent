"""Live form rendering checks; see common.py for setup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tools import browser as browser_tools

pytest.importorskip("browser_use")

from .common import _settings, _store_chooser
from .common import pytestmark as pytestmark

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
            "location (city)": "Sydney, New South Wales, Australia",
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
