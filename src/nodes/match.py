"""Task 3: pick the best-matching resume for the open job description.

The browser node already read the job description into
``state['job_description']``; here the **LLM** (Task 3.2) describes every resume in
the pool and chooses the best fit. Resume files are not modified.

Subtask 3.1: when the LLM finds nothing that matches the job, the agent reuses a
resume it remembered for a similar job, or asks the human to upload one in the
browser (the live session is still registered under ``state['browser_run_id']``),
stores that file in the pool, has the LLM describe it, and remembers it.

Task 16: in strict resume-matching mode (the default) only a **strong** LLM match
is used. Anything else is a clean skip: the node records it on ``task16``, appends
the job title to ``skipped_titles``, and returns ``status="skipped"`` so the graph
opens the next job instead of filling this one. Task 3.1's fallbacks are not used.
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


def _progress_for(state: ApplyState, run_id: str | None):
    """Task 9: the run's status reporter, falling back to the CLI ``print``."""
    from src.tools.browser import get_reporter  # lazy: keeps this node light

    return get_reporter(run_id) or print


async def match(state: ApplyState) -> ApplyState:
    """Choose the best-matching resume for the open job (Task 3)."""
    if state.get("dry_run", True):
        return {"status": "matched", "log": ["match: dry-run, resume selection skipped"]}

    from src.tools.linkedin_best_matching_resume import ensure_resume  # keep light
    from src.tools.linkedin_resume_gate import (  # keep light
        normalize_title,
        record_skip,
        should_skip_job,
    )

    settings = load_settings()
    description = _as_description(state.get("job_description"))
    if not description.is_read:
        # A job description that could not be read is a failure, not a "no resume
        # matched" case: guessing here would wrongly ask the human for a resume and
        # poison the remembered-resume library with an empty job profile.
        return {
            "status": "failed",
            "errors": ["match: the job description could not be read"],
            "log": ["match: no job description to match against"],
        }
    resumes_dir = state.get("resumes_dir") or str(settings.resumes_dir)
    outcome = await ensure_resume(
        description,
        Path(resumes_dir),
        settings,
        page=_page_for(state),
        notify=_progress_for(state, state.get("browser_run_id")),
    )

    log = [
        f"match: resumes_dir={outcome.resumes_dir} found={outcome.resumes_found}",
        f"match: selected={outcome.selected_path} fit={outcome.fit or '(unknown)'}",
        f"match: rationale={outcome.rationale or '(none)'}",
    ]

    # Task 16: a strict-mode no-match is a deliberate skip, not a failure.
    if should_skip_job(outcome, settings):
        task2 = state.get("task2")
        title = (
            (description.title or (task2.job_title if task2 is not None else "") or "").strip()
        )
        task16 = record_skip(state.get("task16"), outcome, task2)
        log.append(
            f"match(task16): skipped {title or 'this job'!r} - no existing resume is "
            f"a strong match (fit={outcome.fit or 'unknown'}; "
            f"{outcome.rationale or 'no rationale'})"
        )
        if outcome.notes:
            log.append(f"match: {outcome.notes}")
        try:
            from src.tools.linkedin_status_overlay import emit_step  # keep light

            emit_step(
                _progress_for(state, state.get("browser_run_id")),
                f"Skipping {title or 'this job'} - no matching resume; "
                "opening the next job.",
            )
        except Exception:  # noqa: BLE001 - status display must never break matching
            pass
        update: ApplyState = {
            "task3": outcome,
            "task16": task16,
            "status": "skipped",
            "log": log,
        }
        # The results list identifies a card by its *card* title, which can be
        # longer than the description heading ("Engineering Team Lead | .NET +
        # React (Verified job)" vs "Engineering Team Lead"). Prefer the card title
        # so the skipped card cannot become eligible again under its full title;
        # fall back to the description title only when Task 2 had none.
        card_title = (task2.job_title if task2 is not None else "") or ""
        skip_title = card_title.strip() or title
        if skip_title:
            update["skipped_titles"] = [normalize_title(skip_title)]
        return update

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
    if outcome.error:
        errors.append(outcome.error)
    elif not outcome.selected_path:
        errors.append("match: no resume could be selected")
    if errors:
        update["errors"] = errors
    return update


__all__ = ["match"]
