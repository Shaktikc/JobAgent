"""Raw renderer input must work during review without bypassing the input lock."""

from __future__ import annotations

import asyncio
import base64
import gc
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.configuration import SessionSettings, Settings
from src.state import Task4Outcome
from src.tools import browser as browser_tools
from src.tools import linkedin_apply_loop as apply_loop
from src.tools import linkedin_status_overlay as status

pytest.importorskip("browser_use")
pytestmark = pytest.mark.skipif(
    not (os.environ.get("AUTOJOB_INPUT_LOCK_LIVE") or os.environ.get("AUTOJOB_SUBMISSION_LIVE")),
    reason="set AUTOJOB_INPUT_LOCK_LIVE=1 or AUTOJOB_SUBMISSION_LIVE=1",
)

_HTML = """<!doctype html><html><body>
<button id="background" onclick="window.backgroundClicks++">Inspect results</button>
<dialog open id="application"><h2>Apply to Example</h2><h3>Review your application</h3>
<button id="safe" onclick="window.reviewClicks++">Inspect attachment</button>
<button id="submit" onclick="window.submitClicks++;this.closest('dialog').close();
document.getElementById('confirmation').showModal()">Submit application</button></dialog>
<dialog id="confirmation"><h2>Application submitted</h2>
<button onclick="this.closest('dialog').close()">Done</button></dialog>
<script>window.reviewClicks=0;window.submitClicks=0;window.backgroundClicks=0;</script>
</body></html>"""


async def _raw_click(page, dispatch, selector):
    point = json.loads(await page.evaluate("""(selector) => {
      const r=document.querySelector(selector).getBoundingClientRect();
      return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2});
    }""", selector))
    for event in ("mousePressed", "mouseReleased"):
        await dispatch(
            {"type": event, **point, "button": "left", "clickCount": 1},
            session_id=await page.session_id,
        )


async def _snapshot(page):
    return json.loads(await page.evaluate("""() => JSON.stringify({
      reviewClicks:reviewClicks,submitClicks:submitClicks,backgroundClicks:backgroundClicks,
      formOpen:document.getElementById('application').open
    })"""))


def _settings(tmp_path, ending):
    return Settings(data_dir=tmp_path / "data", session=SessionSettings(
        headless=True, keep_open_timeout_seconds=0.5 if ending == "timeout" else 0,
        keep_open_poll_seconds=0.02,
    ))


async def _wait(entrypoint, run_id, settings, notify):
    if entrypoint == "release_run":
        return await browser_tools.release_run(
            run_id, Task4Outcome(reached_terminal_step=True), settings, notify,
        )
    return await browser_tools.wait_for_human_close(run_id, settings, notify)


@pytest.mark.parametrize("entrypoint", ["wait_for_human_close", "release_run"])
@pytest.mark.parametrize("ending", ["timeout", "cancel"])
async def test_final_review_accepts_raw_clicks_and_remains_interactive(
    tmp_path, entrypoint, ending,
):
    settings = _settings(tmp_path, ending)
    file = tmp_path / "review.html"
    file.write_text(_HTML, encoding="utf-8")
    browser = browser_tools.build_browser(settings)
    await browser.start()
    page = None
    task = None
    report = {}
    run_id = "task22-review-live"
    evidence = Path("data/debug/task22")
    evidence.mkdir(parents=True, exist_ok=True)
    name = f"review-handoff-{entrypoint}-{ending}"
    try:
        page = await browser.new_page()
        await page.goto(file.as_uri())
        dispatch = page._client.send.Input.dispatchMouseEvent
        lock = await status.ensure_interaction_lock(page)
        assert lock is not None
        await _raw_click(page, dispatch, "#safe")
        report["before"] = await _snapshot(page)
        assert report["before"]["reviewClicks"] == 0, "automation must block raw input"
        browser_tools._ACTIVE_RUNS[run_id] = browser_tools._Run(
            session=SimpleNamespace(is_cdp_connected=True), page=page,
        )
        ready = asyncio.Event()
        task = asyncio.create_task(_wait(
            entrypoint, run_id, settings, lambda _: ready.set(),
        ))
        await asyncio.wait_for(ready.wait(), 5)
        await _raw_click(page, dispatch, "#safe")
        report["during"] = await _snapshot(page)
        assert report["during"]["reviewClicks"] == 1, "final review ignored the human's click"
        if ending == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await asyncio.wait_for(task, 5)
            assert result == ("timeout" if entrypoint == "release_run" else False)
        await lock._refresh()
        await _raw_click(page, dispatch, "#safe")
        report["after"] = await _snapshot(page)
        assert report["after"]["reviewClicks"] == 2, "ending review stranded the input lock"
        assert report["after"]["submitClicks"] == 0, "review must never submit by itself"
        (evidence / f"{name}.png").write_bytes(base64.b64decode(await page.screenshot()))
    finally:
        (evidence / f"{name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        browser_tools.forget_run(run_id)
        if page is not None:
            await status.release_interaction_lock(page)
        await browser.kill()
        gc.collect()
        await asyncio.sleep(0)


async def test_confirmed_manual_submit_restores_the_automation_lock(tmp_path, monkeypatch):
    settings = _settings(tmp_path, "cancel")
    file = tmp_path / "manual.html"
    file.write_text(_HTML, encoding="utf-8")
    browser = browser_tools.build_browser(settings)
    await browser.start()
    page = None
    task = None
    run_id = "task22-manual-lock-live"
    try:
        page = await browser.new_page()
        await page.goto(file.as_uri())
        dispatch = page._client.send.Input.dispatchMouseEvent
        assert await status.ensure_interaction_lock(page) is not None
        await _raw_click(page, dispatch, "#safe")
        assert (await _snapshot(page))["reviewClicks"] == 0
        browser_tools._ACTIVE_RUNS[run_id] = browser_tools._Run(
            session=SimpleNamespace(is_cdp_connected=True), page=page,
        )
        baseline_read = asyncio.Event()
        read = apply_loop._read_state

        async def observe(*args, **kwargs):
            result = await read(*args, **kwargs)
            baseline_read.set()
            return result

        monkeypatch.setattr(apply_loop, "_read_state", observe)
        task = asyncio.create_task(apply_loop.await_human_submit(
            run_id, settings, title="Engineer", company="Example",
        ))
        await asyncio.wait_for(baseline_read.wait(), 5)
        await _raw_click(page, dispatch, "#safe")
        assert (await _snapshot(page))["reviewClicks"] == 1
        await _raw_click(page, dispatch, "#submit")
        assert await asyncio.wait_for(task, 5) == "submitted"
        assert (await _snapshot(page))["submitClicks"] == 1
        await _raw_click(page, dispatch, "#background")
        assert (await _snapshot(page))["backgroundClicks"] == 0, (
            "next-job automation must regain exclusive input after confirmation"
        )
        await status.release_interaction_lock(page)
        await _raw_click(page, dispatch, "#background")
        assert (await _snapshot(page))["backgroundClicks"] == 1
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        browser_tools.forget_run(run_id)
        if page is not None:
            await status.release_interaction_lock(page)
        await browser.kill()
        gc.collect()
        await asyncio.sleep(0)
