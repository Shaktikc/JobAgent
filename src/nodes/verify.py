"""Confirm the acceptance criteria for Tasks 1-4 and finalize the run.

Task 8 adds one more check: when the submit-and-repeat loop ran, it must have
recorded why it stopped (the human submitted, closed the browser, the cap was
reached, or nothing was left to apply to). The human's submission is never treated
as a failure — the agent never clicks **Submit application**.
"""

from __future__ import annotations

from src.state import ApplyState, JobDescription


def _task1_succeeded(state: ApplyState) -> bool:
    outcome = state.get("task1")
    return bool(
        outcome is not None
        and outcome.logged_in
        and outcome.results_found
        and outcome.easy_apply_filter_selected
        and outcome.date_posted_filter_selected
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
        and outcome.reached_terminal_step
        and not outcome.submitted
    )


def _task5_succeeded(state: ApplyState) -> bool:
    """Task 5 passes when every question it asked was resolved, or when it was off.

    The human may answer, skip, or time out — all are acceptable — but a question
    must not be left in limbo with no recorded outcome (which would mean the run
    stopped without noticing).
    """
    outcome = state.get("task5")
    if outcome is None or not outcome.enabled:
        return True
    return outcome.asked == outcome.answered + outcome.skipped + outcome.timed_out


def _task8_succeeded(state: ApplyState) -> bool:
    """Task 8 passes when the loop recorded why it stopped (or never ran).

    A run where the human submitted, closed the browser, timed out, hit the
    jobs-per-run cap, or ran out of unapplied jobs is a **clean** stop and passes;
    the human's submission is never treated as a failure. Hard failures append to
    ``errors`` and are caught before this check.
    """
    outcome = state.get("task8")
    if outcome is None:
        return True
    return bool(outcome.stopped_reason)


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
        and _task5_succeeded(state)
        and _task8_succeeded(state)
    ):
        log = [
            "verify: logged in, search returned results, Easy Apply + Past 24 hours "
            "filters selected, job Easy Apply form opened, best-matching resume "
            "selected, form filled and resume attached (not submitted)"
        ]
        task8 = state.get("task8")
        if task8 is not None:
            log.append(
                f"verify: Task 8 loop submitted {task8.jobs_applied} job(s); "
                f"stopped: {task8.stopped_reason}"
            )
        return {"status": "done", "log": log}

    return {
        "status": "failed",
        "errors": ["verify: acceptance criteria not met"],
        "log": ["verify: acceptance criteria not met"],
    }
