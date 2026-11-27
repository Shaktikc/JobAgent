"""Shared helpers for the Task 11 node crash guard: node calls, reopen, results."""

from __future__ import annotations

import contextlib
import inspect
from collections.abc import Awaitable, Callable
from uuid import uuid4

from src.configuration import Settings
from src.state import ApplyState, JobDescription, Task2Outcome
from src.tools.self_healing.models import CapturedFailure, JobTarget, SelfHealingOutcome
from src.tools.self_healing.recovery import ReopenResult

NodeFn = Callable[[ApplyState], ApplyState | Awaitable[ApplyState]]


async def _call_node(node_fn: NodeFn, state: ApplyState) -> ApplyState:
    """Run a sync or async graph node and return its update."""
    result = node_fn(state)
    if inspect.isawaitable(result):
        return await result
    return result

# How a crash is resumed: ``"job"`` reopens the same job's Easy Apply form (for
# match/await_submit/fill), ``"results"`` reopens the results list the node was
# working on (for next_job), and ``None`` retries the node without a browser (for
# ingest/verify/browse, which launch their own session).
ReopenMode = str | None


def _reporter(run_id: str | None):
    """The run's status reporter, or ``print`` when there is no live run."""
    from src.tools.browser import get_reporter

    return get_reporter(run_id) or print


def _target_with_live_url(target: JobTarget, page_url: str) -> JobTarget:
    """Point the reopen at the page the failing node was actually on."""
    resolved = target.model_copy()
    live = (page_url or "").strip()
    if live.startswith(("http://", "https://")) and "linkedin.com/jobs" in live.lower():
        resolved.url = live
    return resolved


async def _reopen_results(
    target: JobTarget,
    settings: Settings,
    notify,
    captured: CapturedFailure,
) -> ReopenResult:
    """Reopen the results page a ``next_job`` crash was on in a fresh browser."""
    from src.tools.browser import (
        _ACTIVE_RUNS,
        _Run,
        _wait_for_load,
        build_browser,
    )
    from src.tools.linkedin_status_overlay import StatusReporter

    url = (captured.evidence.page_url or target.url or "").strip()
    if not url.startswith(("http://", "https://")):
        return ReopenResult(reason="no results page URL was recorded for the reopen")

    reporter = StatusReporter(emit=notify)
    reporter("self-heal: reopening the results page in a fresh browser...")
    session = build_browser(settings)
    await session.start()
    try:
        page = await session.new_page()
        await page.goto(url)
        await _wait_for_load(page, settings.session.easy_apply_timeout_seconds)
        reporter.bind_page(page)
        run_id = uuid4().hex
        _ACTIVE_RUNS[run_id] = _Run(session=session, page=page, reporter=reporter)
        task2 = Task2Outcome(job_title=target.title, page_url=url)
        description = JobDescription(title=target.title, company=target.company, page_url=url)
        return ReopenResult(run_id=run_id, task2=task2, description=description)
    except Exception as exc:  # noqa: BLE001 - recovery reports why it stopped
        with contextlib.suppress(Exception):
            await session.kill()
        return ReopenResult(reason=f"reopening the results page failed: {exc}")


def _merge_recovered(
    update: ApplyState,
    working: ApplyState,
    outcome: SelfHealingOutcome,
    stage: str,
    log: list[str],
) -> ApplyState:
    """Return the retried node's update plus the new run id and heal summary."""
    merged = dict(update)
    run_id = working.get("browser_run_id")
    if run_id:
        merged["browser_run_id"] = run_id
    merged["self_healing"] = outcome
    merged["log"] = list(merged.get("log") or []) + log + [
        f"self-heal({stage}): recovered and resumed {stage} after "
        f"{outcome.attempts} attempt(s)"
    ]
    return merged


def _failed_result(
    stage: str,
    working: ApplyState,
    outcome: SelfHealingOutcome,
    errors: list[str],
    log: list[str],
) -> ApplyState:
    """A failed node update that still carries the evidence and heal summary."""
    result: ApplyState = {
        "status": "failed",
        "errors": errors + ([f"self-heal({stage}): {outcome.stop_reason}"]
                            if outcome.stop_reason else []),
        "self_healing": outcome,
        "log": log,
    }
    run_id = working.get("browser_run_id")
    if run_id:
        result["browser_run_id"] = run_id
    return result


__all__ = [
    "NodeFn",
    "ReopenMode",
    "_call_node",
    "_failed_result",
    "_merge_recovered",
    "_reopen_results",
    "_reporter",
    "_target_with_live_url",
]
