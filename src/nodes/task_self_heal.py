"""Task-level self-healing for Tasks 1-10.

The graph's crash guard covers **uncaught exceptions**. Several tasks instead
return a hard-stop outcome (for example Task 1 could not log in, Task 2 found no
Easy Apply job, or Task 3's LLM could not choose a resume). Those returned
failures used to end the run without recovery.

:func:`guard_task_node` adds a second layer: after a node returns, it checks the
task outcome with :func:`task_failure_reason`; when the failure is recoverable it
enters the same bounded loop as the crash guard (record evidence, close the
session, repair/test, reopen, retry the task). Non-recoverable stops — a human
login gate, an empty resume pool, or a genuinely unknown answer — are returned
unchanged so the graph stops gracefully instead of retrying blindly.

Task coverage:

* Tasks 1-2: ``browse`` — login/search/filter/Easy Apply form failures.
* Task 3: ``match`` — transient description/LLM errors; the human-upload
  fallback is preserved.
* Task 4: the fill node's existing ``heal_fill_failure`` loop.
* Task 5: best-effort by design — a missing banner/answer is recorded as
  skipped/timed out and never fails the run.
* Tasks 6-7: run inside the Task 2 scan/pagination path, so ``browse``/``next_job``
  recovery covers them.
* Task 8: the graph crash guard for exceptions; clean stops are not retried.
* Tasks 9-10: best-effort by design — a failed panel update is swallowed and a
  failed LLM answer falls through to Task 5.
"""

from __future__ import annotations

import asyncio
import traceback
from collections.abc import Awaitable, Callable

from src.configuration import Settings
from src.nodes.self_heal_guard import heal_node_failure
from src.state import ApplyState
from src.tools.self_healing.recovery import close_run_force

NodeFn = Callable[[ApplyState], Awaitable[ApplyState]]
ReopenMode = str | None

# A returned stop that retrying the whole task cannot fix.
_NON_RECOVERABLE_MARKERS = (
    "login not completed",
    "not a linkedin url",
    "no login url",
    "no search query",
    "no resume could be selected",
    "no resume files",
    "the answer did not match",
    "required questions are unanswered",
)


class TaskStillFailing(RuntimeError):
    """Internal signal: the retried task returned another hard stop."""


def _text(value) -> str:
    return str(value or "").strip()


def _browse_reason(update: ApplyState) -> str:
    """The hard-stop reason from a ``browse`` update, or ``""``."""
    task1 = update.get("task1")
    task2 = update.get("task2")
    description = update.get("job_description")
    if task1 is not None:
        if not bool(getattr(task1, "logged_in", False)):
            return "browse: login not completed"
        if not bool(getattr(task1, "results_found", False)):
            return "browse: job search returned no results"
        if not bool(getattr(task1, "easy_apply_filter_selected", False)):
            return "browse: Easy Apply filter not selected"
        if not bool(getattr(task1, "date_posted_filter_selected", False)):
            return "browse: Date posted filter not selected"
    if task2 is not None:
        if not bool(getattr(task2, "easy_apply_clicked", False)):
            return "browse: no Easy Apply job was opened"
        if not bool(getattr(task2, "application_form_opened", False)):
            return "browse: Easy Apply form did not open"
    if description is not None and not bool(getattr(description, "is_read", False)):
        return "browse: the job description was not read"
    errors = update.get("errors") or []
    if errors:
        return f"browse: {errors[0]}"
    return ""


def _match_reason(update: ApplyState) -> str:
    """The hard-stop reason from a ``match`` update, or ``""``."""
    task3 = update.get("task3")
    if task3 is None:
        errors = update.get("errors") or []
        return f"match: {errors[0]}" if errors else ""
    error = _text(getattr(task3, "error", ""))
    if error:
        return error
    # Task 16: a strict-mode skip is deliberate; reopening the job cannot change
    # the LLM's match decision, so the guard must pass it through untouched.
    if update.get("status") == "skipped" and bool(getattr(task3, "no_match", False)):
        return ""
    if not _text(getattr(task3, "selected_path", "")):
        return "match: no resume could be selected"
    return ""


def _next_job_reason(update: ApplyState) -> str:
    """A recoverable Task 7 pagination stop from a ``next_job`` update, or ``""``.

    A genuine "no next results page" is a clean end and is not returned here;
    only a failed pagination interaction (controls missing, click did not move
    the list) is retried by the task guard.
    """
    task8 = update.get("task8")
    reason = _text(getattr(task8, "stopped_reason", ""))
    lowered = reason.lower()
    if "pagination" in lowered and "no next results page" not in lowered:
        return f"next_job: {reason}"
    return ""


def task_failure_reason(stage: str, update: ApplyState) -> str:
    """Return a task's hard-stop reason for a returned graph update, or ``""``.

    Stages whose success is judged from the returned outcome are checked; the
    fill node owns its own recovery and deliberately returns ``""`` here.
    """
    if not isinstance(update, dict):
        return ""
    if stage == "browse":
        return _browse_reason(update)
    if stage == "match":
        return _match_reason(update)
    if stage == "next_job":
        return _next_job_reason(update)
    return ""


def task_failure_is_recoverable(stage: str, reason: str, update: ApplyState) -> bool:
    """True when reopening the browser and retrying this task could help.

    A human login gate is never retried automatically: the browser is left open
    and the run stops so the human can finish logging in. A ``match`` failure is
    retried only for a transient description/LLM error (``task3.error``); an empty
    or unmatched resume pool keeps its existing graceful stop.
    """
    text = (reason or "").lower()
    if any(marker in text for marker in _NON_RECOVERABLE_MARKERS):
        return False
    if stage == "browse":
        return True
    if stage == "match":
        task3 = update.get("task3")
        return bool(task3 is not None and _text(getattr(task3, "error", "")))
    if stage == "next_job":
        return "pagination" in text
    return False


def _merge_failed_update(result: ApplyState, update: ApplyState) -> ApplyState:
    """Keep a retried task's outcomes/logs when self-healing is exhausted."""
    merged = dict(result)
    for key in ("task1", "task2", "task3", "task8", "task16", "job_description"):
        if update.get(key) is not None:
            merged[key] = update[key]
    merged["errors"] = list(update.get("errors") or merged.get("errors") or [])
    merged["log"] = list(update.get("log") or []) + list(merged.get("log") or [])
    return merged


async def close_self_launched_browser(
    run_id: str | None, settings: Settings
) -> tuple[bool, str]:
    """Close the browser a self-launching node left open when it failed.

    ``browse`` (Tasks 1-2) opens its **own** session: ``start_tasks`` registers a
    run only when the tasks succeed and otherwise only detaches, leaving the
    Chromium window open. With no run id the loop's default close is a no-op, so
    the retry's ``build_browser`` hits the still-held profile lock and refuses to
    launch -- the browse step could never recover (BUG-065). When self-healing is
    about to relaunch, force-close that dedicated-profile browser and clear the
    lock; the failed page's evidence was already captured, so nothing observable
    is lost. A *registered* run is closed through the normal scoped path so a
    concurrent run is never disturbed.
    """
    if run_id:
        return await close_run_force(run_id, settings)

    if not getattr(settings.session, "clean_stale_profile", True):
        # ``build_browser`` tolerates a leftover lock in this mode, so the retry
        # can still launch; leave the failed window open for inspection.
        return True, "left the self-launched browser open (stale-profile cleanup disabled)"

    from src.tools.browser import clean_profile  # lazy: needs the browser extra

    killed = await asyncio.to_thread(clean_profile, settings)
    return True, (
        f"closed {killed} self-launched browser process(es) and cleared the profile lock"
    )


def guard_task_node(stage: str, node_fn: NodeFn, *, reopen: ReopenMode) -> NodeFn:
    """Wrap a task node with exception *and* returned-failure self-healing."""

    async def guarded(state: ApplyState) -> ApplyState:
        if state.get("dry_run", True):
            return await node_fn(state)

        # ``reopen is None`` marks a node that launches its own browser (``browse``)
        # and leaves it open on failure; the loop must close it before retrying.
        close_fn = close_self_launched_browser if reopen is None else None

        try:
            update = await node_fn(state)
        except Exception as exc:  # noqa: BLE001 - the crash guard records and retries
            return await heal_node_failure(
                stage,
                state,
                str(exc),
                traceback.format_exc(),
                node_fn=node_fn,
                reopen=reopen,
                close_fn=close_fn,
            )

        reason = task_failure_reason(stage, update)
        if not reason or not task_failure_is_recoverable(stage, reason, update):
            return update

        last = {"update": update}

        async def retry_fn(working: ApplyState) -> ApplyState:
            retried = await node_fn(working)
            retry_reason = task_failure_reason(stage, retried)
            if retry_reason:
                last["update"] = retried
                raise TaskStillFailing(retry_reason)
            return retried

        result = await heal_node_failure(
            stage,
            state,
            reason,
            "",
            node_fn=retry_fn,
            reopen=reopen,
            close_fn=close_fn,
        )
        outcome = result.get("self_healing")
        if outcome is not None and not bool(getattr(outcome, "recovered", False)):
            result = _merge_failed_update(result, last["update"])
        return result

    guarded.__name__ = getattr(node_fn, "__name__", stage)
    guarded.__doc__ = getattr(node_fn, "__doc__", None)
    return guarded


__all__ = [
    "TaskStillFailing",
    "close_self_launched_browser",
    "guard_task_node",
    "task_failure_is_recoverable",
    "task_failure_reason",
]
