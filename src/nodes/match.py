"""Task 3: pick the best-matching resume for the open job description.

This node is deterministic and offline. The browser node already read the job
description into ``state['job_description']``; here we read the resumes folder,
score every resume, and select the highest fit. Resume files are never modified.
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


def match(state: ApplyState) -> ApplyState:
    """Choose the best-matching resume for the open job (Task 3)."""
    if state.get("dry_run", True):
        return {"status": "matched", "log": ["match: dry-run, resume selection skipped"]}

    from src.tools.resumes import select_best_resume  # local import keeps the node light

    description = _as_description(state.get("job_description"))
    resumes_dir = state.get("resumes_dir") or str(load_settings().resumes_dir)
    outcome = select_best_resume(description, Path(resumes_dir))

    log = [
        f"match: resumes_dir={outcome.resumes_dir} found={outcome.resumes_found}",
        f"match: selected={outcome.selected_path} score={outcome.selected_score}",
        f"match: rationale={outcome.rationale or '(none)'}",
    ]
    if outcome.notes:
        log.append(f"match: {outcome.notes}")

    update: ApplyState = {"task3": outcome, "status": "matched", "log": log}

    errors: list[str] = []
    if outcome.resumes_found == 0:
        errors.append(f"match: no resumes available in {outcome.resumes_dir}")
    elif not outcome.selected_path:
        errors.append("match: no resume could be selected")
    if errors:
        update["errors"] = errors
    return update


__all__ = ["match"]
