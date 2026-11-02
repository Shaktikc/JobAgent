"""Live form stale radio checks; see common.py for setup."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tools import browser as browser_tools
from src.tools.llm_answers import QuestionDecision
from src.tools.self_healing.fingerprint import fill_failure_reason

pytest.importorskip("browser_use")

from .common import _settings
from .common import pytestmark as pytestmark

_STALE_ROLE_RADIO_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Task 4 stale radio</title></head>
<body>
<div class="artdeco-modal jobs-easy-apply-modal" role="dialog">
  <div class="artdeco-modal__content">
    <h3>Apply to Hays</h3>
    <p>Have you implemented and integrated AI voice, conversational
       AI or chatbot platforms into production environments?*</p>
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
