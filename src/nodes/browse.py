"""Drive the browser: Task 1 (log in, search, filter) then Task 2 (select Easy Apply).

The real work is delegated to :func:`src.tools.browser.run_agent`, which is
imported lazily so the heavy ``browser`` extra stays optional. That single call
owns one browser session for the whole flow, including the human login gate, so
the login cookies and the job list carry from Task 1 into Task 2.
"""

from __future__ import annotations

from src.state import ApplyState


async def browse(state: ApplyState) -> ApplyState:
    """Run the login + search + filter + select-Easy-Apply flow."""
    if state.get("dry_run", True):
        return {
            "status": "dry_run",
            "log": ["browse: dry-run, browser not launched"],
        }

    from src.tools.browser import run_agent  # lazy: needs the `browser` extra

    try:
        result = await run_agent(
            state["url"],
            state.get("search_query") or "",
            progress=print,
        )
    except Exception as exc:  # noqa: BLE001 - surface any setup/launch failure
        return {
            "status": "failed",
            "errors": [f"browse: {exc}"],
            "log": ["browse: browser run failed"],
        }

    task1, task2 = result.task1, result.task2
    log = [
        "browse: task1 "
        f"logged_in={task1.logged_in} "
        f"results_found={task1.results_found} "
        f"results_count={task1.results_count} "
        f"easy_apply_filter={task1.easy_apply_filter_selected}",
        "browse: task2 "
        f"jobs_seen={task2.jobs_seen} "
        f"job_index={task2.job_index} "
        f"easy_apply_clicked={task2.easy_apply_clicked} "
        f"form_opened={task2.application_form_opened} "
        f"skipped={task2.skipped_jobs}",
    ]
    if task1.notes:
        log.append(f"browse: {task1.notes}")
    if task2.notes:
        log.append(f"browse: {task2.notes}")

    update: ApplyState = {"task1": task1, "task2": task2, "status": "applied", "log": log}

    errors: list[str] = []
    if not task1.logged_in:
        errors.append(f"browse: login not completed (url={task1.page_url or state['url']})")
    elif not task1.results_found:
        errors.append(
            f"browse: job search returned no results (url={task1.page_url or state['url']})"
        )
    elif not task1.easy_apply_filter_selected:
        errors.append(f"browse: Easy Apply filter not selected (url={task1.page_url})")
    elif not task2.easy_apply_clicked:
        errors.append(f"browse: no job Easy Apply button was clicked (url={task2.page_url})")
    elif not task2.application_form_opened:
        errors.append(f"browse: Easy Apply form did not open (url={task2.page_url})")

    if errors:
        update["errors"] = errors
    return update
