"""Confirm the acceptance criteria for Task 1 + Task 2 and finalize the run."""

from __future__ import annotations

from src.state import ApplyState


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


def verify(state: ApplyState) -> ApplyState:
    """Decide the terminal status from what the browser observed."""
    if state.get("errors"):
        return {"status": "failed", "log": ["verify: run finished with errors"]}

    if state.get("dry_run", True):
        return {"status": "done", "log": ["verify: dry-run complete (browser not launched)"]}

    if _task1_succeeded(state) and _task2_succeeded(state):
        return {
            "status": "done",
            "log": [
                "verify: logged in, search returned results, Easy Apply filter selected, "
                "job Easy Apply form opened"
            ],
        }

    return {
        "status": "failed",
        "errors": ["verify: acceptance criteria not met"],
        "log": ["verify: acceptance criteria not met"],
    }
