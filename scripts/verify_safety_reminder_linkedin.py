"""Live check: the "Job search safety reminder" is closed and the job is skipped.

Logs in and runs the default search (``DEFAULT_SEARCH_QUERY``), then opens a job
known to show the reminder after Easy Apply, calls ``open_easy_apply_form`` and
asserts the reminder was closed and the job reported as skipped. Never submits;
if a real form opens instead it is closed/discarded.
"""

import argparse
import asyncio

from src.configuration import load_settings
from src.state import DEFAULT_LOGIN_URL, DEFAULT_SEARCH_QUERY, Task2Outcome
from src.tools.browser import close_run, get_run, start_tasks
from src.tools.linkedin_easy_apply_open import open_easy_apply_form
from src.tools.linkedin_resume_gate import close_easy_apply_form
from src.tools.linkedin_safety_reminder import safety_reminder_open

DEFAULT_JOB_ID = "4495067576"  # Wave Visas - Artificial Intelligence Engineer


async def verify(job_id: str) -> None:
    settings = load_settings()
    _result, run_id = await start_tasks(
        DEFAULT_LOGIN_URL, DEFAULT_SEARCH_QUERY, settings, progress=print, open_form=False
    )
    assert run_id, "login/search did not leave a browser session open"
    run = get_run(run_id)
    page = run.page
    try:
        await page.goto(
            f"https://www.linkedin.com/jobs/search-results/?currentJobId={job_id}"
        )
        await asyncio.sleep(6)
        outcome = Task2Outcome(job_title=f"job {job_id}", job_selected=True)
        opened, outcome = await open_easy_apply_form(page, settings, print, outcome)
        print(
            f"opened={opened} clicked={outcome.easy_apply_clicked} "
            f"reminder_skipped={outcome.safety_reminder_skipped} notes={outcome.notes!r}"
        )
        if opened:
            await close_easy_apply_form(page, settings, print)
            raise AssertionError("a real Easy Apply form opened; reminder not shown")
        assert outcome.easy_apply_clicked, "Easy Apply was not clicked"
        assert outcome.safety_reminder_skipped, "the safety reminder was not detected"
        assert not await safety_reminder_open(page), "the reminder is still open"
        print("PASS: safety reminder closed and the job is skipped")
    finally:
        await close_run(run_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", default=DEFAULT_JOB_ID)
    args = parser.parse_args()
    asyncio.run(verify(args.job_id))
