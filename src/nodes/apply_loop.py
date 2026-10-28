"""Task 8: the graph's submit-and-repeat loop.

Two nodes drive the loop after Task 4 fills a job to its terminal step:

* :func:`await_submit` — leave the browser open and wait for the human to submit
  (or close it). The agent **never** clicks **Submit application**. On a detected
  submission it records the job on the Task 8 outcome and, unless the jobs-per-run
  cap is reached, lets the graph continue.
* :func:`next_job` — back on the results list, re-read the cards, skip the
  **"Applied"** ones (Task 6), paginate when a whole page is Applied (Task 7), and
  open the first unapplied **Easy Apply** job (reading its description, Task 3) so
  ``match`` and ``fill`` can run for it again.

The heavy browser layer is imported lazily (the ``browser`` extra stays optional),
mirroring the other nodes.
"""

from __future__ import annotations

from src.configuration import load_settings
from src.state import ApplyState, Task8JobRecord, Task8Outcome


async def await_submit(state: ApplyState) -> ApplyState:
    """Wait for the human to submit the open application (Task 8, step 1)."""
    if state.get("dry_run", True):
        return {"status": "submitted", "log": ["await_submit: dry-run, nothing to wait for"]}

    run_id = state.get("browser_run_id")
    if not run_id:
        return {
            "status": "failed",
            "errors": ["await_submit: no open browser session"],
            "log": ["await_submit: no session to wait on"],
        }

    from src.tools.browser import get_reporter  # lazy: keeps this node light
    from src.tools.linkedin_apply_loop import await_human_submit  # lazy: needs the extra

    settings = load_settings()
    task2 = state.get("task2")
    task3 = state.get("task3")
    description = state.get("job_description")
    title = (task2.job_title if task2 else "") or ""

    # Let a crash propagate: the graph's self-heal guard records it, closes the
    # stale browser, repairs/tests, and retries this same step (Task 11).
    result = await await_human_submit(
        run_id, settings, progress=get_reporter(run_id) or print, title=title
    )

    task8 = state.get("task8") or Task8Outcome()
    task8.iterations += 1
    task8.max_jobs = settings.session.max_jobs_per_run
    log = [f"await_submit: human submit result={result} (job={title!r})"]

    if result == "submitted":
        task8.jobs_applied += 1
        task8.jobs.append(
            Task8JobRecord(
                index=task2.job_index if task2 else None,
                title=title,
                company=(description.company if description else ""),
                resume_path=((task3.selected_path if task3 else "") or ""),
                outcome="submitted",
            )
        )
        log.append(f"await_submit: jobs submitted this run={task8.jobs_applied}")
        cap = task8.max_jobs
        if cap and task8.jobs_applied >= cap:
            task8.stopped_reason = f"reached the jobs-per-run cap ({cap})"
            log.append(f"await_submit: stopping - {task8.stopped_reason}")
    elif result == "closed":
        task8.stopped_reason = "the human closed the browser"
        log.append(f"await_submit: stopping - {task8.stopped_reason}")
    else:  # "timeout"
        task8.stopped_reason = "timed out waiting for the human to submit"
        log.append(f"await_submit: stopping - {task8.stopped_reason}")

    return {"task8": task8, "status": "submitted", "log": log}


async def next_job(state: ApplyState) -> ApplyState:
    """Open the next unapplied job on the results list (Task 8, step 2)."""
    if state.get("dry_run", True):
        return {"status": "selected", "log": ["next_job: dry-run, browser not touched"]}

    run_id = state.get("browser_run_id")
    if not run_id:
        return {
            "status": "failed",
            "errors": ["next_job: no open browser session"],
            "log": ["next_job: no session to select from"],
        }

    from src.tools.browser import get_reporter  # lazy: keeps this node light
    from src.tools.linkedin_apply_loop import open_next_job  # lazy: needs the extra

    settings = load_settings()

    # Task 16: a skip is not an application. Stop at the configured skip cap so a
    # run that matches nothing cannot scan forever.
    task16 = state.get("task16")
    skip_cap = settings.session.max_skipped_jobs_per_run
    if task16 is not None and skip_cap and task16.jobs_skipped >= skip_cap:
        task8 = state.get("task8") or Task8Outcome()
        task8.stopped_reason = f"reached the skipped-jobs cap ({skip_cap})"
        log = [f"next_job: stopping - {task8.stopped_reason}"]
        return {"task8": task8, "status": "stopped", "log": log}

    previous = state.get("task2")
    skip_title = (previous.job_title if previous else "") or ""
    skipped_titles = list(state.get("skipped_titles") or [])
    skipping = state.get("status") == "skipped"

    # Let a crash propagate: the graph's self-heal guard records it, closes the
    # stale browser, repairs/tests, and retries this same step from the results
    # list (Task 11).
    result = await open_next_job(
        run_id,
        settings,
        progress=get_reporter(run_id) or print,
        skip_title=skip_title,
        skip_titles=skipped_titles,
        close_form=skipping,
    )

    task2 = result.task2
    log = [
        "next_job: task2 "
        f"jobs_seen={task2.jobs_seen} "
        f"job_index={task2.job_index} "
        f"easy_apply_clicked={task2.easy_apply_clicked} "
        f"form_opened={task2.application_form_opened} "
        f"applied_skipped={task2.applied_jobs_skipped} "
        f"pages_visited={task2.pages_visited}",
    ]
    if skipped_titles:
        log.append(f"next_job: excluding {len(skipped_titles)} previously skipped job(s)")
    if task2.notes:
        log.append(f"next_job: {task2.notes}")

    if result.opened:
        log.append(
            f"next_job: opened {task2.job_title!r} "
            f"(company={result.description.company!r}, "
            f"{len(result.description.body)} description chars)"
        )
        # Keep the last successfully opened job in task2/job_description so
        # ``verify`` sees a completed job, not this pass's search attempt.
        return {
            "task2": task2,
            "job_description": result.description,
            "status": "applied",
            "log": log,
        }

    task8 = state.get("task8") or Task8Outcome()
    task8.stopped_reason = result.reason or "no unapplied job could be opened"
    log.append(f"next_job: stopping - {task8.stopped_reason}")
    return {"task8": task8, "status": "stopped", "log": log}


__all__ = ["await_submit", "next_job"]
