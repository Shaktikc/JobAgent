"""Verify Task 20 in the dedicated LinkedIn browser without submitting.

Default: inspect only. --walk runs production correction/logging/cleanup, using
prefilled values and grounded stored answers. --continue-next also selects the
next eligible posting after a successful skip, leaving resume matching to the
normal graph. Evidence excludes applicant answers and stays in data/debug/.
"""

import argparse
import asyncio
import base64
import json
from uuid import uuid4

from browser_use import BrowserSession

from src.configuration import load_settings
from src.state import JobAnswerContext
from src.tools.answers import load_answers
from src.tools.browser import _ACTIVE_RUNS, _Run, forget_run
from src.tools.linkedin_apply_loop import open_next_job
from src.tools.linkedin_best_matching_resume import read_job_description
from src.tools.linkedin_easy_apply_fill.form_queries import read_form
from src.tools.linkedin_easy_apply_fill.form_walk import _task4_on_page
from src.tools.linkedin_validation.continuation import results_url
from src.tools.linkedin_validation.detection import read_rejections


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdp-url", required=True)
    parser.add_argument("--walk", action="store_true")
    parser.add_argument("--continue-next", action="store_true")
    parser.add_argument("--query", default="software engineer")
    parser.add_argument(
        "--date-range", choices=["past_24_hours", "past_week"], default="past_24_hours"
    )
    args = parser.parse_args()
    if args.continue_next and not args.walk:
        parser.error("--continue-next requires --walk")
    settings = load_settings()
    settings.session.ask_human = False
    folder = settings.debug_dir / "task20_linkedin"
    folder.mkdir(parents=True, exist_ok=True)
    browser = BrowserSession(cdp_url=args.cdp_url, keep_alive=True)
    await browser.start()
    run_id = f"task20-verification-{uuid4()}"
    try:
        page = None
        for candidate in await browser.get_pages():
            if "linkedin.com/jobs/" in await candidate.get_url():
                if (await read_form(candidate))[0]:
                    page = candidate
                    break
        if page is None:
            raise RuntimeError("No LinkedIn jobs tab in the dedicated browser")
        opened, title, fields, step = await read_form(page)
        if not opened:
            raise RuntimeError("Open an Easy Apply form before verification")
        initial = await read_rejections(page, fields)
        report = {
            "url_before": await page.get_url(),
            "step_before": step,
            "errors_before": [
                {"question": row["question"], "message": row["message"]} for row in initial
            ],
        }
        (folder / "before.png").write_bytes(base64.b64decode(await page.screenshot()))
        if args.walk:
            description = await read_job_description(page)
            # Reuse the real page in the existing next-job helper. Remove only
            # this temporary registry handle when detaching from the browser.
            _ACTIVE_RUNS[run_id] = _Run(session=browser, page=page)
            messages = []
            outcome = await _task4_on_page(
                page,
                browser,
                None,
                load_answers(settings.answers_file),
                settings,
                messages.append,
                context=JobAnswerContext(job_description=description),
            )
            assert not outcome.submitted
            report["outcome"] = outcome.model_dump(exclude={"fields", "unknown_fields"})
            if outcome.validation.issues and not outcome.validation.skipped:
                raise RuntimeError(outcome.validation.error or "Validation skip did not finish")
            if outcome.validation.skipped and args.continue_next:
                result = await open_next_job(
                    run_id,
                    settings,
                    skip_job_ids=[outcome.validation.job_id],
                    results_url=results_url("", args.query, args.date_range),
                    date_range=args.date_range,
                    preferred_range=args.date_range,
                )
                report["continuation"] = {
                    "opened": result.opened,
                    "reason": result.reason,
                    "title": result.task2.job_title,
                    "url": result.task2.page_url,
                    "form_opened": result.task2.application_form_opened,
                    "date_range": result.task2.date_range_used,
                    "original_company": description.company,
                }
                assert result.opened, result.reason
                assert str(outcome.validation.job_id) not in str(result.task2.page_url)
        report["url_after"] = await page.get_url()
        (folder / "after.png").write_bytes(base64.b64decode(await page.screenshot()))
        name = "walk" if args.walk else "inspect"
        path = folder / f"{name}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print("TASK20_VERIFICATION " + json.dumps(report, ensure_ascii=True))
        print(f"Evidence: {path}")
    finally:
        forget_run(run_id)
        await browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
