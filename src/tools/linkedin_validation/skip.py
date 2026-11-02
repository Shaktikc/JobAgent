"""Persist an unresolved validation before discarding; record it as a skip."""

from datetime import UTC, datetime

from src.state.validation import Task20Outcome
from src.tools.linkedin_resume_gate import close_easy_apply_form
from src.tools.linkedin_status_overlay import emit_step
from src.tools.linkedin_validation.identity import current_job_link
from src.tools.linkedin_validation.journal import append_skip


async def persist_and_close(page, state, outcome, settings, notify) -> None:
    """Failure to save or close is a safe stop, never a self-healing retry."""
    result = outcome.validation
    if not result.issues or result.skipped:
        return
    try:
        result.job_id, result.job_url = await current_job_link(page, state)
        if not result.job_url:
            raise ValueError("could not capture a direct job link; leaving Easy Apply open")
        description = state.get("job_description")
        path = settings.data_dir / "invalid_input_skips.json"
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "job_url": result.job_url,
            "job_id": result.job_id,
            "title": description.title if description else outcome.job_context.job_title,
            "company": description.company if description else outcome.job_context.company,
            "reason": "invalid_input",
            "errors": [issue.model_dump() for issue in result.issues],
            "correction_attempted": result.correction_attempted,
            "retry_count": result.retry_count,
            "correction_failure": result.correction_failure,
        }
        append_skip(path, record)
        result.logged, result.log_path = True, str(path)
        emit_step(notify, f"Saved invalid-input log for {result.job_url}; closing Easy Apply...")
        result.modal_closed = await close_easy_apply_form(page, settings, notify)
        if not result.modal_closed:
            raise RuntimeError("Easy Apply did not close; saved job link preserved")
        emit_step(notify, f"Skipping unresolved invalid input - saved {result.job_url}")
    except Exception as exc:  # a journal/cleanup failure must never discard or relaunch
        result.error = f"Task 20: {exc} (job: {result.job_url or 'link unavailable'})"
        notify(result.error)
        emit_step(notify, result.error)


def record_validation_skip(state, outcome) -> dict:
    """Update graph accounting only after both required side effects succeeded."""
    result = outcome.validation
    if not result.skipped:
        return {
            "status": "failed",
            "errors": [result.error or "Task 20: validation skip incomplete"],
            "log": ["fill: unresolved validation stopped safely; no automatic retry"],
        }
    aggregate = (state.get("task20") or Task20Outcome()).model_copy(deep=True)
    aggregate.jobs_skipped += 1
    aggregate.skipped.append(result.model_copy(deep=True))
    return {
        "status": "skipped",
        "task20": aggregate,
        "skipped_job_ids": [result.job_id],
        "log": [f"fill: invalid_input skipped; saved {result.job_url} in {result.log_path}"],
    }
