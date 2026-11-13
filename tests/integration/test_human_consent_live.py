"""Single consent controls must survive LinkedIn replacing marked DOM nodes."""

import json
import os

import pytest

from src.configuration import SessionSettings, Settings
from src.tools.answers import load_answers
from src.tools.browser import build_browser
from src.tools.linkedin_ask_human import ask_human_for_answer
from src.tools.linkedin_ask_human.answer_js import _READ_FORM_ANSWER_JS

pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_FILL_LIVE"), reason="set AUTOJOB_FILL_LIVE=1"
)


@pytest.mark.parametrize("checked", [True, False])
async def test_single_consent_without_marker_or_name(tmp_path, checked, monkeypatch):
    settings = Settings(
        data_dir=tmp_path / "data", session=SessionSettings(headless=True)
    )
    monkeypatch.setattr("src.tools.linkedin_ask_human.flow._SAVED_VISIBLE_SECONDS", 0)
    browser = build_browser(settings)
    await browser.start()
    try:
        fixture = tmp_path / "consent.html"
        fixture.write_text(
            '<label><input type="checkbox" checked>I consent</label>'
            '<dialog open><h2>Apply to Example</h2><section>'
            '<p>You agree to the privacy notice.*</p><div><div>'
            '<input id="consent" type="checkbox" '
            + ('checked' if checked else '')
            + '><label for="consent"></label></div><p>I consent</p></div>'
            '</section><button>Review</button></dialog>',
            encoding="utf-8",
        )
        page = await browser.new_page(fixture.as_uri())
        result = json.loads(await page.evaluate(
            _READ_FORM_ANSWER_JS, ["lost-marker"], "",
            "You agree to the privacy notice.*", ["I consent"],
        ))
        assert result["value"] == ("I consent" if checked else "")
        assert result["done"] is checked
        if checked:
            answer = await ask_human_for_answer(
                page, "You agree to the privacy notice.*", "checkbox", "I consent",
                settings, lambda _: None, markers=["lost-marker"], options=["I consent"],
            )
            assert answer == "I consent"
            assert list(load_answers(settings.answers_file).values()) == ["I consent"]
    finally:
        await browser.kill()
