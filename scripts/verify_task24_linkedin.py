"""Inspect and verify required-question recovery in the dedicated LinkedIn browser.

This check never submits an application. Launch once with --launch, then attach
with --cdp-url to inspect the current real Easy Apply step.
"""

import argparse
import asyncio
import base64
import json

from browser_use import BrowserSession

from scripts.task24_recovery import prepare, recover
from src.configuration import load_settings
from src.tools.browser import _marker_element, build_browser
from src.tools.forms import pick_next_button
from src.tools.linkedin_easy_apply_fill.form_queries import read_form, read_form_buttons
from src.tools.linkedin_easy_apply_open import open_easy_apply_form
from src.tools.linkedin_resume_gate import close_easy_apply_form
from src.tools.linkedin_validation.detection import read_rejections


async def verify(args):
    settings = load_settings()
    folder = settings.debug_dir / "task24"
    folder.mkdir(parents=True, exist_ok=True)
    browser = (
        build_browser(settings)
        if args.launch
        else BrowserSession(cdp_url=args.cdp_url, keep_alive=True)
    )
    await browser.start()
    try:
        print("CDP_URL:", browser.cdp_url, flush=True)
        pages = await browser.get_pages()
        page = None
        for candidate in pages:
            if "linkedin.com/jobs/" in await candidate.get_url():
                page = candidate
                break
        if page is None and args.launch:
            page = await browser.new_page("https://www.linkedin.com/jobs/")
            await asyncio.sleep(5)
        if page is None:
            raise RuntimeError("Open a LinkedIn jobs tab in the dedicated browser")
        if args.job_url:
            await page.goto(args.job_url)
            await asyncio.sleep(4)
        if args.reset:
            if not await close_easy_apply_form(page, settings, print):
                raise RuntimeError("Could not close the previous verification form")
        if args.open or args.reset:
            print("OPEN:", await open_easy_apply_form(page, settings, print), flush=True)
            await asyncio.sleep(1)
        if args.until_question:
            for _ in range(10):
                current = await read_form(page)
                if any(args.until_question in field.get("question", "") for field in current[2]):
                    break
                button = pick_next_button(await read_form_buttons(page))
                if button is None:
                    raise RuntimeError(
                        "The requested question was not reached; stopping before Submit"
                    )
                element = await _marker_element(page, "data-autojob-btn", button["marker"])
                await element.evaluate("() => this.scrollIntoView({block:'center'})")
                await element.click()
                await asyncio.sleep(1)
            else:
                raise RuntimeError("Question walk exceeded ten steps")
        if args.prepare:
            await prepare(page, settings, args.leave_question)
        if args.next:
            button = pick_next_button(await read_form_buttons(page))
            if button is None:
                raise RuntimeError("No enabled Next/Review button; stopping before Submit")
            element = await _marker_element(page, "data-autojob-btn", button["marker"])
            await element.evaluate("() => this.scrollIntoView({block:'center'})")
            await element.click()
            await asyncio.sleep(1)
        if args.recover:
            await recover(page, settings, args.recover, folder, args.human_timeout)
        opened, title, fields, step = await read_form(page)
        report = {
            "url": await page.get_url(),
            "open": opened,
            "title": title,
            "step": step,
            "fields": [
                {
                    key: f.get(key)
                    for key in ("kind", "type", "question", "name", "option", "required", "checked")
                }
                for f in fields
            ],
            "issues": [
                {key: issue.get(key) for key in ("question", "message")}
                for issue in await read_rejections(page, fields)
            ],
            "job_links": await page.evaluate("""() => Array.from(
                document.querySelectorAll('a[href*="/jobs/view/"]')).slice(0, 25)
                .map(a => ({text:a.innerText.trim(),
                    url:a.getAttribute('href').split('?')[0]}))"""),
        }
        (folder / "inspection.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        try:
            screenshot = await asyncio.wait_for(page.screenshot(), 10)
            (folder / "inspection.png").write_bytes(base64.b64decode(screenshot))
        except TimeoutError:
            print("Screenshot timed out; JSON evidence is preserved.", flush=True)
        markup = await page.evaluate("""() => {
            const root = document.querySelector('dialog[open],.jobs-easy-apply-modal');
            return root ? root.outerHTML : '';
        }""")
        (folder / "inspection.html").write_text(str(markup), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True), flush=True)
        if args.hold:
            print("Holding the dedicated browser for follow-up verification.", flush=True)
            await asyncio.Event().wait()
    finally:
        await browser.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--launch", action="store_true")
    group.add_argument("--cdp-url")
    parser.add_argument("--job-url")
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--hold", action="store_true")
    parser.add_argument("--next", action="store_true")
    parser.add_argument("--recover", choices=["automatic", "human", "disabled"])
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--leave-question", default="")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--until-question")
    parser.add_argument("--human-timeout", type=float, default=120)
    asyncio.run(verify(parser.parse_args()))
