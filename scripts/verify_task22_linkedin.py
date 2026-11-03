"""Inspect Task 22's real LinkedIn submit preflight without submitting or filling."""

import argparse
import asyncio
import base64
import json
from pathlib import Path

from browser_use import BrowserSession

from src.configuration import load_settings
from src.tools.browser import _detach_session, build_browser
from src.tools.linkedin_auto_submit import _is_linkedin_jobs_url, inspect_submit_control
from src.tools.linkedin_easy_apply_fill.form_queries import read_form, read_form_buttons
from src.tools.linkedin_job_selection import _task2_on_page


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--cdp-url")
    source.add_argument(
        "--launch", action="store_true", help="Launch the dedicated project profile",
    )
    parser.add_argument(
        "--open-form", action="store_true", help="Open an Easy Apply form for inspection only",
    )
    args = parser.parse_args()
    browser = (build_browser(load_settings()) if args.launch
               else BrowserSession(cdp_url=args.cdp_url, keep_alive=True))
    await browser.start()
    try:
        page = None
        for candidate in await browser.get_pages():
            if _is_linkedin_jobs_url(await candidate.get_url()):
                page = candidate
                break
        if page is None:
            if not args.launch:
                raise RuntimeError("No LinkedIn jobs tab is open in the dedicated browser")
            page = await browser.new_page()
            await page.goto("https://www.linkedin.com/jobs/")
            await asyncio.sleep(3)
        if args.open_form:
            await page.goto(
                "https://www.linkedin.com/jobs/search/?keywords=software%20engineer&f_AL=true"
            )
            await asyncio.sleep(4)
            selected = await _task2_on_page(page, load_settings(), print)
            if not selected.application_form_opened:
                raise RuntimeError(f"No Easy Apply form opened: {selected.notes}")
        opened, title, fields, step = await read_form(page)
        buttons = await read_form_buttons(page)
        control, _, reason = await inspect_submit_control(page)
        report = {
            "url": await page.get_url(), "form_open": opened, "title": title, "step": step,
            "fields": len(fields), "required_fields": sum(bool(f.get("required")) for f in fields),
            "buttons": [{"text": b["text"], "disabled": b.get("disabled")} for b in buttons],
            "runtime_submit_control_ready": control is not None, "blocked_reason": reason,
            "scope": "current DOM only; full fill outcome not checked; no submission attempted",
        }
        folder = Path("data/debug/task22")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "linkedin-inspection.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8",
        )
        (folder / "linkedin-inspection.png").write_bytes(base64.b64decode(await page.screenshot()))
        print(json.dumps(report, ensure_ascii=True))
    finally:
        await _detach_session(browser)


if __name__ == "__main__":
    asyncio.run(main())
