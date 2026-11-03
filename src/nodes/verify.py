"""Confirm the acceptance criteria for Tasks 1-4 and finalize the run.

Task 8 adds one more check: when the submit-and-repeat loop ran, it must have
recorded why it stopped (the human submitted, closed the browser, the cap was
reached, or nothing was left to apply to). Task 22 also permits confirmed automatic
submission when the human selected it at startup.

Task 16 adds a clean stop for strict resume matching: when the last job was
skipped because no existing resume matched, the run is done (not failed) as long
as the loop recorded its stop reason and no error was raised.
"""

from __future__ import annotations

from src.date_range import DEFAULT_DATE_RANGE, date_range_label, normalize_date_range
from src.state import ApplyState, JobDescription


def _requested_date_range(state: ApplyState) -> str:
    """The range the user chose at startup, defaulting to Past 24 hours."""
    return normalize_date_range(state.get("date_range") or "") or DEFAULT_DATE_RANGE


def _task1_succeeded(state: ApplyState) -> bool:
    outcome = state.get("task1")
    return bool(
        outcome is not None
        and outcome.logged_in
        and outcome.results_found
        and outcome.easy_apply_filter_selected
        and outcome.date_posted_filter_selected
        and outcome.date_posted_filter_value == _requested_date_range(state)
    )


def _task2_succeeded(state: ApplyState) -> bool:
    """A job that offers Easy Apply was selected (a skip leaves the form closed).

    The match-first flow records ``job_selected`` without clicking; after a
    selected match the ``open_form`` node records the click and opened form. Both
    are valid Task 2 outcomes.
    """
    outcome = state.get("task2")
    if outcome is None:
        return False
    return bool(
        (outcome.job_selected and outcome.easy_apply_button_found)
        or (outcome.easy_apply_clicked and outcome.application_form_opened)
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
        and (not outcome.submitted or (
            state.get("submission_mode") == "auto" and outcome.submission_attempted
            and state.get("task8") and state["task8"].jobs_applied > 0
        ))
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


def _task16_skipped_to_the_end(state: ApplyState) -> bool:
    """True when the run ended with a deliberate Task 16 skip, not a failure.

    The last opened job has no selected resume (that is why it was skipped), so
    the normal Task 3/Task 4 checks cannot describe the run. A run is clean when
    the loop recorded why it stopped and the last job was a strict-mode no-match;
    jobs skipped this way never fill a form and are never counted as applications.
    """
    task16 = state.get("task16")
    task3 = state.get("task3")
    task8 = state.get("task8")
    return bool(
        task16 is not None
        and task16.enabled
        and task16.jobs_skipped >= 1
        and task3 is not None
        and task3.no_match
        and not task3.selected_path
        and _task1_succeeded(state)
        and _task2_succeeded(state)
        and _task5_succeeded(state)
        and task8 is not None
        and task8.stopped_reason
    )


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

    task4, task20, task8 = state.get("task4"), state.get("task20"), state.get("task8")
    if (state.get("submission_mode") == "auto" and task8
            and task8.last_submission_status in {
                "blocked", "unconfirmed", "closed", "interrupted",
            }):
        return {"status": "needs_review", "log": [
            f"verify: automatic submission needs manual review; {task8.stopped_reason}",
            f"verify: confirmed submissions this run={task8.jobs_applied}",
        ]}
    if (task4 and task4.validation.skipped and task20 and task20.jobs_skipped
            and task8 and task8.stopped_reason and _task1_succeeded(state)
            and _task2_succeeded(state) and _task5_succeeded(state)):
        return {"status": "done", "log": [
            f"verify: Task 20 logged and skipped {task20.jobs_skipped} invalid-input job(s); "
            f"stopped: {task8.stopped_reason}",
        ]}

    if (
        _task1_succeeded(state)
        and _task2_succeeded(state)
        and _task3_succeeded(state)
        and _task4_succeeded(state)
        and _task5_succeeded(state)
        and _task8_succeeded(state)
    ):
        range_label = date_range_label(_requested_date_range(state))
        log = [
            f"verify: logged in, search returned results, Easy Apply + {range_label} "
            "filters selected, job Easy Apply form opened, best-matching resume "
            "selected, form filled and resume attached "
            + ("(automatic submission confirmed)" if state.get("task4").submitted
               else "(not submitted)")
        ]
        task8 = state.get("task8")
        if task8 is not None:
            log.append(
                f"verify: Task 8 loop submitted {task8.jobs_applied} job(s); "
                f"stopped: {task8.stopped_reason}"
            )
        return {"status": "done", "log": log}

    if _task16_skipped_to_the_end(state):
        task16 = state.get("task16")
        task8 = state.get("task8")
        return {
            "status": "done",
            "log": [
                f"verify: strict resume matching skipped {task16.jobs_skipped} job(s) "
                "with no matching resume; no application was started for them "
                "(not submitted)",
                f"verify: Task 8 loop submitted {task8.jobs_applied} job(s); "
                f"stopped: {task8.stopped_reason}",
            ],
        }

    return {
        "status": "failed",
        "errors": ["verify: acceptance criteria not met"],
        "log": ["verify: acceptance criteria not met"],
    }
