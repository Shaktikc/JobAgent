"""Inspect or verify Task 25 on real LinkedIn without submitting applications."""

import argparse
import asyncio
import base64
import json

from browser_use import BrowserSession

from scripts.task24_recovery import prepare
from scripts.task25_conversion import exercise, next_step
from src.configuration import load_settings
from src.tools.linkedin_easy_apply_fill.form_queries import read_form, read_form_buttons
from src.tools.linkedin_validation.detection import read_rejections


async def verify(args):
    settings = load_settings()
    folder = settings.debug_dir / "task25"
    folder.mkdir(parents=True, exist_ok=True)
    settings.session.easy_apply_timeout_seconds = 5
    browser = BrowserSession(cdp_url=args.cdp_url, keep_alive=True)
    await browser.start()
    try:
        page = None
        for candidate in await browser.get_pages():
            if "linkedin.com/jobs/" in await candidate.get_url():
                page = candidate
                break
        if page is None:
            raise RuntimeError("Open LinkedIn jobs in the dedicated browser first")
        if args.prepare:
            await prepare(page, settings)
        for _ in range(args.next):
            await next_step(page)
        if args.exercise:
            await exercise(page, settings, args.exercise, folder)
        current = await read_form(page)
        report = {
            "url": (await page.get_url()).split("?")[0],
            "open": current[0],
            "title": current[1],
            "step": current[3],
            "fields": [
                {
                    **{
                        key: field.get(key)
                        for key in ("question", "kind", "type", "required", "name")
                    },
                    "has_answer": bool(field.get("value") or field.get("checked")),
                }
                for field in current[2]
            ],
            "buttons": await read_form_buttons(page),
            "issues": [
                {key: issue.get(key) for key in ("question", "message")}
                for issue in await read_rejections(page, current[2])
            ],
        }
        (folder / "inspection.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)
        try:
            shot = await asyncio.wait_for(page.screenshot(), 8)
            (folder / "inspection.png").write_bytes(base64.b64decode(shot))
        except TimeoutError:
            print("Screenshot timeout; DOM and JSON evidence retained.", flush=True)
    finally:
        await browser.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdp-url", required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--next", type=int, default=0)
    parser.add_argument("--exercise", metavar="QUESTION_FRAGMENT")
    asyncio.run(verify(parser.parse_args()))
