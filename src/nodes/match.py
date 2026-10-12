"""Task 3: pick the best-matching resume for the open job description.

The browser node already read the job description into
``state['job_description']``; here we read the resumes folder, score every
resume, and select the highest fit. Resume files are not modified.

Subtask 3.1: when nothing in the folder matches the job at all, the agent reuses
a resume it remembered for a similar job, or asks the human to upload one in the
browser (the live session is still registered under ``state['browser_run_id']``),
stores that file in the pool, and remembers it for similar jobs.
"""

from __future__ import annotations

from pathlib import Path

from src.configuration import load_settings
from src.state import ApplyState, JobDescription


def _as_description(value) -> JobDescription:
    if isinstance(value, JobDescription):
        return value
    if isinstance(value, dict):
        return JobDescription(**value)
    return JobDescription()


def _page_for(state: ApplyState):
    """The live page for this run, if the browser session is still open."""
    run_id = state.get("browser_run_id")
    if not run_id:
        return None
    from src.tools.browser import get_run  # lazy: keeps this node light

    run = get_run(run_id)
    return run.page if run is not None else None


async def match(state: ApplyState) -> ApplyState:
    """Choose the best-matching resume for the open job (Task 3)."""
    if state.get("dry_run", True):
        return {"status": "matched", "log": ["match: dry-run, resume selection skipped"]}

    from src.tools.linkedin_best_matching_resume import ensure_resume  # keep light

    settings = load_settings()
    description = _as_description(state.get("job_description"))
    resumes_dir = state.get("resumes_dir") or str(settings.resumes_dir)
    outcome = await ensure_resume(
        description,
        Path(resumes_dir),
        settings,
        page=_page_for(state),
        notify=print,
    )

    log = [
        f"match: resumes_dir={outcome.resumes_dir} found={outcome.resumes_found}",
        f"match: selected={outcome.selected_path} score={outcome.selected_score}",
        f"match: rationale={outcome.rationale or '(none)'}",
    ]
    if outcome.no_match:
        log.append("match(task3.1): no resume matched the job")
    if outcome.reused_from_library:
        log.append(f"match(task3.1): reused {outcome.reused_from_library} from a similar job")
    if outcome.asked_human:
        log.append(
            f"match(task3.1): asked the human; uploaded={outcome.human_resume_path or 'none'}"
        )
    if outcome.notes:
        log.append(f"match: {outcome.notes}")

    update: ApplyState = {"task3": outcome, "status": "matched", "log": log}

    errors: list[str] = []
    if not outcome.selected_path:
        if outcome.resumes_found == 0:
            errors.append(f"match: no resumes available in {outcome.resumes_dir}")
        else:
            errors.append("match: no resume could be selected")
    if errors:
        update["errors"] = errors
    return update


__all__ = ["match"]
