"""Continue the job scan after an unsubmitted form failed to attach its resume."""

from src.state import ApplyState, Task4Outcome, Task8Outcome
from src.tools.linkedin_validation.identity import job_id_from_url


def skip_missing_resume(state: ApplyState, outcome: Task4Outcome, settings) -> ApplyState:
    task2 = state.get("task2")
    description = state.get("job_description")
    title = (task2.job_title if task2 else "") or (description.title if description else "")
    urls = [
        outcome.page_url,
        task2.page_url if task2 else "",
        description.page_url if description else "",
    ]
    identity = next(filter(None, map(job_id_from_url, urls)), "")
    if identity:
        if identity in (state.get("skipped_job_ids") or []):
            return {}
        exclusion = {"skipped_job_ids": [identity]}
    elif title.strip() and title.strip() not in (state.get("skipped_titles") or []):
        exclusion = {"skipped_titles": [title.strip()]}
    else:
        return {}

    outcome.skipped_missing_resume = True
    task8 = (state.get("task8") or Task8Outcome()).model_copy(deep=True)
    task8.max_jobs = settings.session.max_jobs_per_run
    task8.missing_resume_skips += 1
    return {
        **exclusion,
        "task8": task8,
        "status": "skipped",
        "log": [
            f"fill: skipping {title or identity!r} because the selected resume was not attached"
        ],
    }
