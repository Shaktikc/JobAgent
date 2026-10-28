"""Task 2b: open Easy Apply after a resume has been selected (Task 16).

``browse`` and ``next_job`` now select a job and read its description without
clicking Easy Apply. This node is the only place that clicks the form open, and
the graph reaches it only when ``match`` selected a resume. A skipped job goes
straight to ``next_job``, so its Easy Apply button is never clicked.
"""

from __future__ import annotations

from src.configuration import load_settings
from src.state import ApplyState


async def open_form(state: ApplyState) -> ApplyState:
    """Click the selected job's Easy Apply button and wait for its form."""
    if state.get("dry_run", True):
        return {"status": "matched", "log": ["open_form: dry-run, form not opened"]}

    run_id = state.get("browser_run_id")
    if not run_id:
        return {
            "status": "failed",
            "errors": ["open_form: no open browser session"],
            "log": ["open_form: no session to open Easy Apply in"],
        }

    task2 = state.get("task2")
    if task2 is None or not (task2.job_selected or task2.application_form_opened):
        return {
            "status": "failed",
            "errors": ["open_form: no selected job to apply to"],
            "log": ["open_form: no selected job"],
        }

    from src.tools.browser import get_reporter, get_run  # lazy: needs the extra
    from src.tools.linkedin_easy_apply_open import open_easy_apply_form  # lazy

    settings = load_settings()
    run = get_run(run_id)
    if run is None:
        return {
            "status": "failed",
            "errors": ["open_form: the browser session is no longer available"],
            "log": ["open_form: browser session is gone"],
        }

    opened, task2 = await open_easy_apply_form(
        run.page,
        settings,
        get_reporter(run_id) or print,
        task2,
    )
    log = [
        "open_form: "
        f"job={task2.job_title!r} opened={opened} "
        f"clicked={task2.easy_apply_clicked}"
    ]
    if task2.notes:
        log.append(f"open_form: {task2.notes}")
    update: ApplyState = {
        "task2": task2,
        "status": "form_open" if opened else "failed",
        "log": log,
    }
    if not opened:
        update["errors"] = [
            f"open_form: {task2.notes or 'Easy Apply form did not open'}"
        ]
    return update


__all__ = ["open_form"]
