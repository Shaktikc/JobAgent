"""Opt-in live-browser regression test for BUG-083 (input lock vs human turn).

A watch tick (or the tail of an automation input command) that was already in
flight when a human turn began used to write ``Input.setIgnoreInputEvents(true)``
*after* the turn had unlocked the page, so the human could not type into the
Easy Apply form for the whole turn.

Enable it (the ``browser`` extra must be installed)::

    $env:AUTOJOB_INPUT_LOCK_LIVE="1"
    uv run pytest tests/integration/test_human_turn_unlock_live.py -s
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from src.configuration import SessionSettings, Settings
from src.tools import browser as browser_tools
from src.tools import linkedin_status_overlay as status

pytest.importorskip("browser_use")

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("AUTOJOB_INPUT_LOCK_LIVE"),
        reason="set AUTOJOB_INPUT_LOCK_LIVE=1 to run the live input-lock test",
    ),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

_FIXTURE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Input lock</title></head><body>
<h2>Additional Questions</h2>
<label for="graphql">How many years of work experience do you have with GraphQL?*</label>
<input id="graphql" type="text" maxlength="20">
</body></html>
"""


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        session=SessionSettings(
            headless=True,
            step_delay_seconds=0,
            post_click_wait_seconds=0,
            ask_human=True,
            keep_open_timeout_seconds=1,
        ),
        data_dir=tmp_path / "data",
    )


class _IgnoredWrites:
    """Record the real CDP ``setIgnoreInputEvents`` writes the lock performs."""

    def __init__(self, input_client) -> None:
        self.writes: list[bool] = []
        self._input = input_client
        self._original = input_client.setIgnoreInputEvents

    def install(self) -> None:
        async def recorder(params, session_id=None):
            await self._original(params, session_id=session_id)
            self.writes.append(bool(params.get("ignore")))

        self._input.setIgnoreInputEvents = recorder

    def restore(self) -> None:
        self._input.setIgnoreInputEvents = self._original


async def test_a_watch_tick_in_flight_does_not_re_lock_a_human_turn(tmp_path: Path) -> None:
    """BUG-083 on a real Chromium renderer: the last write must stay unlocked."""
    settings = _settings(tmp_path)
    fixture = tmp_path / "lock.html"
    fixture.write_text(_FIXTURE, encoding="utf-8")

    browser = browser_tools.build_browser(settings)
    await browser.start()
    page = None
    lock = None
    recorder = None
    try:
        page = await browser.new_page()
        await page.goto(fixture.as_uri())
        await browser_tools._wait_for_load(page, 10)

        lock = await status.ensure_interaction_lock(page)
        assert lock is not None
        if lock._task is not None:  # drive one watch tick by hand
            lock._task.cancel()
            await asyncio.gather(lock._task, return_exceptions=True)
            lock._task = None
        recorder = _IgnoredWrites(page._client.send.Input)
        recorder.install()

        inspect_started = asyncio.Event()
        inspect_release = asyncio.Event()

        async def slow_probe() -> bool:
            inspect_started.set()
            await inspect_release.wait()
            return False

        lock._on_login_page = slow_probe  # type: ignore[method-assign]
        tick = asyncio.create_task(lock._refresh())
        await asyncio.wait_for(inspect_started.wait(), 5)

        await status.begin_human_turn(page)
        assert recorder.writes[-1] is False, "the human turn must unlock the page"

        inspect_release.set()
        await tick
        assert recorder.writes[-1] is False, (
            "a watch tick that began before the human turn re-locked the page (BUG-083)"
        )

        # The renderer accepted the final write: an explicit lock/unlock pair
        # through the same client still round-trips.
        await page._client.send.Input.setIgnoreInputEvents(
            {"ignore": False}, session_id=await page.session_id
        )
        assert recorder.writes[-1] is False
    finally:
        if recorder is not None:
            recorder.restore()
        if lock is not None:
            await status.release_interaction_lock(page)
        await browser.stop()


async def test_automation_command_tail_does_not_re_lock_a_human_turn(tmp_path: Path) -> None:
    """BUG-083: a human turn that starts mid-click wins over the command tail."""
    settings = _settings(tmp_path)
    fixture = tmp_path / "lock-tail.html"
    fixture.write_text(_FIXTURE, encoding="utf-8")

    browser = browser_tools.build_browser(settings)
    await browser.start()
    page = None
    lock = None
    recorder = None
    try:
        page = await browser.new_page()
        await page.goto(fixture.as_uri())
        await browser_tools._wait_for_load(page, 10)
        lock = await status.ensure_interaction_lock(page)
        assert lock is not None
        if lock._task is not None:
            lock._task.cancel()
            await asyncio.gather(lock._task, return_exceptions=True)
            lock._task = None
        recorder = _IgnoredWrites(page._client.send.Input)
        recorder.install()

        await page.evaluate(
            """() => {
              window.__clicked = 0;
              document.querySelector('h2').addEventListener(
                'click', () => { window.__clicked += 1; }
              );
            }"""
        )
        # Find the h2 on screen and click it through the wrapped Input client.
        box = await page.evaluate(
            """() => {
              const r = document.querySelector('h2').getBoundingClientRect();
              return JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2});
            }"""
        )
        point = json.loads(box)
        input_client = page._client.send.Input
        session_id = await page.session_id
        await input_client.dispatchMouseEvent(
            {"type": "mousePressed", "x": point["x"], "y": point["y"],
             "button": "left", "clickCount": 1},
            session_id=session_id,
        )
        await status.begin_human_turn(page)
        await input_client.dispatchMouseEvent(
            {"type": "mouseReleased", "x": point["x"], "y": point["y"],
             "button": "left", "clickCount": 1},
            session_id=session_id,
        )

        assert recorder.writes[-1] is False, (
            "the tail of an automation click re-locked the page during a human turn"
        )
        assert str(await page.evaluate("() => String(window.__clicked)")) == "1"
    finally:
        if recorder is not None:
            recorder.restore()
        if lock is not None:
            await status.release_interaction_lock(page)
        await browser.stop()
