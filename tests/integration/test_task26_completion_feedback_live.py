"""Checkbox completion feedback must state the action needed to resume."""

import json
import os

import pytest

from src.configuration import SessionSettings, Settings
from src.tools.browser import build_browser
from src.tools.linkedin_ask_human.banner_js import _SHOW_UNKNOWN_JS
from src.tools.linkedin_ask_human.completion_js import _UPDATE_PENDING_JS

pytestmark = pytest.mark.skipif(not os.environ.get("AUTOJOB_FILL_LIVE"), reason="live opt-in")


async def test_detected_choices_explain_how_to_continue(tmp_path):
    browser = build_browser(Settings(data_dir=tmp_path, session=SessionSettings(headless=True)))
    await browser.start()
    try:
        page = await browser.new_page()
        await page.evaluate(_SHOW_UNKNOWN_JS, "WFH requirements?", "Desktop, Internet, Landline")
        await page.evaluate(_UPDATE_PENDING_JS, "Desktop, Internet, Landline", True)
        result = json.loads(
            await page.evaluate("""() => JSON.stringify({
            status: document.getElementById('autojob-unknown-status').textContent,
            disabled: document.getElementById('autojob-unknown-done').disabled
        })""")
        )
        assert result["status"] == (
            "Selected: Desktop, Internet, Landline. Click Done to save and continue."
        )
        assert not result["disabled"]
        await page.evaluate(_UPDATE_PENDING_JS, "", True)
        assert (
            str(
                await page.evaluate(
                    "() => document.getElementById('autojob-unknown-done').disabled"
                )
            ).lower()
            == "true"
        )
    finally:
        await browser.kill()
