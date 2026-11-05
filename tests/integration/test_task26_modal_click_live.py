"""Real pointer interaction with Done inside a native modal dialog."""

import json
import os

import pytest

from src.configuration import SessionSettings, Settings
from src.tools.browser import _marker_element, build_browser
from src.tools.linkedin_ask_human.answer_js import _WATCH_FORM_ANSWER_JS
from src.tools.linkedin_ask_human.banner_js import _SHOW_UNKNOWN_JS
from src.tools.linkedin_ask_human.completion_js import _UPDATE_PENDING_JS

pytestmark = pytest.mark.skipif(not os.environ.get("AUTOJOB_FILL_LIVE"), reason="live opt-in")


@pytest.mark.parametrize("action", ["done", "skip"])
async def test_banner_buttons_receive_real_clicks_inside_native_modal(tmp_path, action):
    browser = build_browser(Settings(data_dir=tmp_path, session=SessionSettings(headless=True)))
    await browser.start()
    try:
        fixture = tmp_path / "modal.html"
        fixture.write_text("""<dialog id="apply" style="width:70vw;height:70vh">
          <h2>Apply to Example</h2><input data-autojob-fill="a">
        </dialog><script>
          const modal=document.getElementById('apply'); modal.showModal();
          modal.addEventListener('click', e => {
            if(e.target===modal) window.dismissed=true;
          });
        </script>""")
        page = await browser.new_page(fixture.as_uri())
        await page.evaluate(_WATCH_FORM_ANSWER_JS, ["a"])
        await page.evaluate(_SHOW_UNKNOWN_JS, "WFH requirements?", "Desktop, Internet, Landline")
        await page.evaluate(_UPDATE_PENDING_JS, "Desktop, Internet, Landline", True)
        button = await _marker_element(page, "id", "autojob-unknown-" + action)
        await button.click()
        state = json.loads(
            await page.evaluate("""() => JSON.stringify({
          confirmed: !!window.__autojobFormAnswer.confirmed,
          skipped: document.getElementById('autojob-unknown').dataset.autojobState==='skipped',
          dismissed: !!window.dismissed
        })""")
        )
        assert not state["dismissed"]
        assert state["confirmed" if action == "done" else "skipped"]
    finally:
        await browser.kill()
