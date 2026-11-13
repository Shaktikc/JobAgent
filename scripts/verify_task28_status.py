"""Exercise Task 2 and the latest-line panel in Chromium, without submitting.

Run with ``uv run python -m scripts.verify_task28_status`` for the existing
Task 2 fixture, or add ``--linkedin`` to use the dedicated logged-in profile.
Evidence is saved under data/debug/task28; the browser stays open.
"""

import argparse
import asyncio
import base64
import json
from pathlib import Path

from src.configuration import SessionSettings, Settings, load_settings
from src.tools.browser import _detach_session, build_browser
from src.tools.linkedin_job_selection import _task2_on_page
from src.tools.linkedin_status_overlay import StatusReporter, sanitize_panel_text

_READ = """() => JSON.stringify((() => {
  const box = document.getElementById('autojob-status');
  return {
    text: document.getElementById('autojob-status-current')?.textContent,
    heading: document.getElementById('autojob-status-heading')?.textContent,
    count: document.querySelectorAll('#autojob-status').length,
    pointer: box && getComputedStyle(box).pointerEvents,
    border: box && getComputedStyle(box).borderColor,
    live: box?.getAttribute('aria-live'),
    top: box?.matches(':popover-open')
    , innerHeight, outerHeight,
    bottom: box?.getBoundingClientRect().bottom,
    bodyBottom: document.getElementById('autojob-status-current')
      ?.getBoundingClientRect().bottom
  };
})())"""


async def verify(linkedin=False, open_form=False):
    folder = Path("data/debug/task28").resolve() / ("linkedin" if linkedin else "fixture")
    folder.mkdir(parents=True, exist_ok=True)
    settings = load_settings() if linkedin else Settings(
        data_dir=folder / "browser-data",
        session=SessionSettings(headless=False, post_click_wait_seconds=0),
    )
    settings.session.headless = False
    browser = build_browser(settings)
    reporter = None
    lines, observations = [], []

    def emit(message):
        lines.append(message)
        print(message, flush=True)

    await browser.start()
    try:
        page = await browser.new_page()
        if linkedin:
            await page.goto(
                "https://www.linkedin.com/jobs/search/?keywords=software%20engineer&f_AL=true"
            )
            await asyncio.sleep(5)
        else:
            from tests.integration.test_task2_skip_applied_live import _results_page

            fixture = folder / "jobs.html"
            fixture.write_text(_results_page([
                ("Backend Engineer", "Applied"), ("Data Engineer", "Viewed"),
            ]), encoding="utf-8")
            await page.goto(fixture.as_uri())
        reporter = StatusReporter(emit=emit)
        reporter("Please wait - checking the latest activity panel...")
        reporter.bind_page(page)

        async def check(name):
            expected = sanitize_panel_text(lines[-1])
            for _ in range(100):
                state = json.loads(await page.evaluate(_READ))
                if state.get("text") == expected:
                    break
                await asyncio.sleep(0.05)
            assert state.get("text") == expected, (expected, state)
            assert state["count"] == 1 and state["pointer"] == "none"
            assert state["live"] == "polite" and state["top"]
            assert state["innerHeight"] < state["outerHeight"]
            assert state["bodyBottom"] <= state["bottom"] <= state["innerHeight"]
            observations.append({"case": name, "terminal": lines[-1], **state})
            (folder / f"{name}.png").write_bytes(base64.b64decode(await page.screenshot()))
            return state

        await check("bound")
        outcome = await _task2_on_page(page, settings, reporter, open_form=False)
        await check("task2")
        if open_form:
            from src.tools.linkedin_easy_apply_open import open_easy_apply_form

            opened, _ = await open_easy_apply_form(page, settings, reporter, outcome)
            assert opened, "The selected job's Easy Apply form did not open"
            reporter("Please wait - filling form step 3...")  # display probe only
            await check("form-visible")
        if not linkedin:
            assert outcome.applied_jobs_skipped == 1
            assert outcome.job_title == "Data Engineer"
        # Replay actual Task 2 log lines individually: a rapid burst may coalesce.
        for name, needle in [("skip", "already applied; skipping"), ("opening", "opening job")]:
            matching = [line for line in lines if needle in line]
            if matching:
                reporter(matching[-1])
                await check(name)
            elif not linkedin:
                raise AssertionError(f"Task 2 did not emit {needle}")
        reporter.llm("verifying the status panel", "display check, no model request")
        assert (await check("llm"))["border"] == "rgb(106, 63, 181)"
        for i in range(100):
            reporter(f"Panel burst verification {i}")
        await check("burst")
        reporter("Waiting for you - review the latest activity panel.")
        assert (await check("waiting"))["border"] == "rgb(148, 98, 0)"
        reporter("pending cleanup")
        await reporter.clear()
        await asyncio.sleep(0.1)
        assert json.loads(await page.evaluate(_READ))["count"] == 0
        report = {"url": await page.get_url(), "outcome": outcome.model_dump(),
                  "observations": observations, "cleanup_passed": True, "submitted": False}
        (folder / "evidence.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"PASS: evidence saved to {folder}", flush=True)
    finally:
        if reporter is not None:
            await reporter.clear()
        await _detach_session(browser)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linkedin", action="store_true")
    parser.add_argument("--open-form", action="store_true", help="Open form; never fill or submit")
    args = parser.parse_args()
    asyncio.run(verify(args.linkedin, args.open_form))
