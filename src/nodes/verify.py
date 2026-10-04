"""Confirm the acceptance criteria for Tasks 1-4 and finalize the run."""

from __future__ import annotations

from src.state import ApplyState, JobDescription


def _task1_succeeded(state: ApplyState) -> bool:
    outcome = state.get("task1")
    return bool(
        outcome is not None
        and outcome.logged_in
        and outcome.results_found
        and outcome.easy_apply_filter_selected
    )


def _task2_succeeded(state: ApplyState) -> bool:
    outcome = state.get("task2")
    return bool(
        outcome is not None and outcome.easy_apply_clicked and outcome.application_form_opened
    )


def _task3_succeeded(state: ApplyState) -> bool:
    outcome = state.get("task3")
    if outcome is None:
        return False
    description = outcome.job_description
    description_read = isinstance(description, JobDescription) and description.is_read
    return bool(
        outcome.selected_path
        and outcome.rationale
        and outcome.resumes_found >= 1
        and len(outcome.candidates) == outcome.resumes_found
        and description_read
    )


def _task4_succeeded(state: ApplyState) -> bool:
    outcome = state.get("task4")
    return bool(
        outcome is not None
        and outcome.form_open
        and outcome.resume_attached
        and outcome.filled_fields == outcome.known_fields
        and not outcome.submitted
    )


def verify(state: ApplyState) -> ApplyState:
    """Decide the terminal status from what the browser and matcher observed."""
    if state.get("errors"):
        return {"status": "failed", "log": ["verify: run finished with errors"]}

    if state.get("dry_run", True):
        return {"status": "done", "log": ["verify: dry-run complete (browser not launched)"]}

    if (
        _task1_succeeded(state)
        and _task2_succeeded(state)
        and _task3_succeeded(state)
        and _task4_succeeded(state)
    ):
        return {
            "status": "done",
            "log": [
                "verify: logged in, search returned results, Easy Apply filter selected, "
                "job Easy Apply form opened, best-matching resume selected, "
                "form filled and resume attached (not submitted)"
            ],
        }

    return {
        "status": "failed",
        "errors": ["verify: acceptance criteria not met"],
        "log": ["verify: acceptance criteria not met"],
    }
