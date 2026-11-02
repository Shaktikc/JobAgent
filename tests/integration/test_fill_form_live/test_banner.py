"""Live form banner checks; see common.py for setup."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.state import Task5Outcome
from src.tools import browser as browser_tools

pytest.importorskip("browser_use")

from .common import _settings
from .common import pytestmark as pytestmark
from .test_human_text import _ANSWER_IN_FORM_JS

_BANNER_ON_TOP_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Task 5 on top</title></head>
<body>
<div id="overlay" style="position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,.5)"></div>
<div class="artdeco-modal jobs-easy-apply-modal" role="dialog"
     style="position:fixed;inset:60px;z-index:100000;background:#fff">
  <div class="artdeco-modal__content">
    <div class="fb-dash-form-element">
      <label for="notice">Notice period*</label>
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
