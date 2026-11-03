"""Inspect the affected posting and preserve metadata without submitting it."""

import argparse
import asyncio
import base64
import json
from pathlib import Path

from browser_use import BrowserSession

from src.configuration import load_settings
from src.tools.browser import _detach_session, build_browser
from src.tools.linkedin_easy_apply_fill.form_queries import read_form, read_form_buttons
from src.tools.linkedin_job_apply_button import find_job_apply_button
from src.tools.linkedin_submission import read_submission_state


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", type=int, required=True)
    parser.add_argument("--cdp-url")
    parser.add_argument("--title", default="")
    parser.add_argument("--company", default="")
    parser.add_argument("--search-layout", action="store_true")
    args = parser.parse_args()
    browser = (BrowserSession(cdp_url=args.cdp_url, keep_alive=True) if args.cdp_url
               else build_browser(load_settings()))
    await browser.start()
    try:
        page = await browser.new_page()
        url = f"https://www.linkedin.com/jobs/view/{args.job_id}/"
        if args.search_layout:
            url = ("https://www.linkedin.com/jobs/search-results/"
                   f"?currentJobId={args.job_id}&keywords=software%20engineer"
                   "&origin=SEMANTIC_SEARCH_LANDING_PAGE&f_TPR=r86400&f_AL=true")
        await page.goto(url)
        await asyncio.sleep(4)
        # Read before any card tagging: submission can re-render the SDUI cards
        # and remove the markers created by the selection/fill phase.
        submission = await read_submission_state(page, args.title, args.company)
        apply_label = ""
        if not (submission["status_submitted"] or submission["card_applied"]):
            _, apply_label = await find_job_apply_button(page)
        opened, title, fields, step = await read_form(page)
        report = {
            "job_id": args.job_id, "url": await page.get_url(), "apply_label": apply_label,
            "form_open": opened, "title": title, "step": step,
            "fields": [{"question": f["question"], "kind": f["kind"],
                        "required": f["required"]} for f in fields],
            "buttons": await read_form_buttons(page),
            "submission": submission,
            "candidate_cards": json.loads(await page.evaluate("""(company) => JSON.stringify(
              Array.from(document.querySelectorAll('div[role="button"],[data-autojob-card],'
                + 'li.jobs-search-results__list-item'))
                .filter(el => company && (el.innerText || '').toLowerCase()
                  .includes(company.toLowerCase()) && (el.innerText || '').length < 1600)
                .slice(0,5).map(el => ({tag:el.tagName,role:el.getAttribute('role'),
                  lines:(el.innerText || '').split('\\n').filter(Boolean).slice(0,7)}))
            )""", args.company)),
        }
        folder = Path("data/debug/task22")
        folder.mkdir(parents=True, exist_ok=True)
        name = "reported-job-search" if args.search_layout else "reported-job"
        (folder / f"{name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (folder / f"{name}.png").write_bytes(base64.b64decode(await page.screenshot()))
        print(json.dumps(report, ensure_ascii=True))
    finally:
        await _detach_session(browser)


if __name__ == "__main__":
    asyncio.run(main())
