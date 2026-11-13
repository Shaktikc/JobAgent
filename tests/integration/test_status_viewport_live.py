"""Opt-in regression: a headed browser's viewport must fit its visible window.

AUTOJOB_STATUS_VIEWPORT_LIVE=1 uv run pytest -s tests/integration/test_status_viewport_live.py
The browser stays open; screenshots and metrics go to data/debug/task28/viewport.
"""

import asyncio
import base64
import json
import os
from pathlib import Path

import pytest

from src.configuration import SessionSettings, Settings
from src.tools.browser import _detach_session, build_browser
from src.tools.linkedin_status_overlay import StatusReporter

pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_STATUS_VIEWPORT_LIVE"), reason="opt-in headed browser check",
)


async def test_panel_body_stays_in_the_visible_resized_window(tmp_path):
    folder = Path("data/debug/task28/viewport").resolve()
    folder.mkdir(parents=True, exist_ok=True)
    stage = os.environ.get("AUTOJOB_VIEWPORT_STAGE", "after")
    fixture = tmp_path / "viewport.html"
    fixture.write_text(
        '<title>Task 28 viewport regression</title><h1>Viewport regression</h1>'
        '<dialog open>Easy Apply form fixture</dialog>', encoding="utf-8",
    )
    settings = Settings(data_dir=tmp_path / "data", session=SessionSettings(headless=False))
    browser = build_browser(settings)
    reporter = None
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(fixture.as_uri())
        # Exercise the configured tab-created handler deterministically. Actor
        # new_page() alone can miss the async event in an isolated harness.
        from browser_use.browser.events import TabCreatedEvent

        await browser.on_TabCreatedEvent(TabCreatedEvent(
            target_id=page._target_id, url=fixture.as_uri(),
        ))
        reporter = StatusReporter(emit=print, page=page)
        reporter("Please wait - filling form step 3...")
        window = await browser.cdp_client.send.Browser.getWindowForTarget(
            {"targetId": page._target_id},
        )
        observations = []
        for height in (640, 540):
            await browser.cdp_client.send.Browser.setWindowBounds({
                "windowId": window["windowId"],
                "bounds": {"windowState": "normal"},
            })
            await browser.cdp_client.send.Browser.setWindowBounds({
                "windowId": window["windowId"],
                "bounds": {"width": 900, "height": height},
            })
            await asyncio.sleep(0.5)
            metrics = json.loads(await page.evaluate("""() => JSON.stringify({
                innerHeight, outerHeight, innerWidth, outerWidth,
                text: document.getElementById('autojob-status-current').textContent,
                box: document.getElementById('autojob-status').getBoundingClientRect().toJSON(),
                body: document.getElementById('autojob-status-current')
                    .getBoundingClientRect().toJSON()
            })"""))
            observations.append(metrics)
            (folder / f"{stage}-{height}.png").write_bytes(
                base64.b64decode(await page.screenshot()),
            )
        (folder / f"{stage}.json").write_text(json.dumps(observations, indent=2))
        print(json.dumps(observations, indent=2))
        for metrics in observations:
            assert metrics["text"] == "Please wait - filling form step 3..."
            assert metrics["innerHeight"] < metrics["outerHeight"], (
                "Emulated page extends below the actual browser window", metrics,
            )
            assert 0 <= metrics["body"]["top"] < metrics["body"]["bottom"]
            assert metrics["box"]["bottom"] <= metrics["innerHeight"]
            assert metrics["body"]["bottom"] <= metrics["innerHeight"]
        assert observations[1]["innerHeight"] < observations[0]["innerHeight"]
    finally:
        if reporter:
            await reporter.clear()
        await _detach_session(browser)
