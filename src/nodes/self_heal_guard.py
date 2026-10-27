"""Always-on crash guard for the graph nodes (Task 11).

The fill node owns its own recovery path. Every other node used to catch a
browser/runtime exception and turn it into a plain ``status="failed"`` update, so
a crash in ``next_job``, ``await_submit``, ``browse`` or ``match`` ended the run
without ever recording evidence, closing the stale browser, repairing, or
resuming the same step.

:func:`guard_node` wraps a node and applies the bounded self-healing loop to any
**uncaught** exception:

1. Capture evidence and record the failure (BUG-NNN) while the failed page is
   still open.
2. Close the run cleanly (force-close, verify the profile lock cleared).
3. Run the optional repair command and tests.
4. Reopen the browser (the same job form, or the same results page) and retry
   the **same node** with the recovered run id.
5. Stop after the configured attempt cap, preserving the evidence and marking
   the bug open.

Nothing here clicks **Submit application**.
"""

from __future__ import annotations

import contextlib
import inspect
import traceback
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import uuid4

from src.configuration import PROJECT_ROOT, Settings, load_settings
from src.state import ApplyState, JobDescription, Task2Outcome
from src.tools.self_healing.buglog import mark_exhausted, mark_fixed, record_failure
from src.tools.self_healing.capture import capture_failure
from src.tools.self_healing.models import (
    CapturedFailure,
    FailureRecord,
    HealingAttempt,
    JobTarget,
    SelfHealingOutcome,
)
from src.tools.self_healing.recovery import (
    ReopenResult,
    close_run_force,
    job_target_from_state,
    reload_runtime_modules,
    reopen_same_job,
    run_repair_and_test,
)

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

    notify("self-heal: reopening the results page in a fresh browser...")
    session = build_browser(settings)
    await session.start()
    try:
        page = await session.new_page()
        reporter = StatusReporter(emit=notify)
        reporter.bind_page(page)
        await page.goto(url)
        await _wait_for_load(page, settings.session.easy_apply_timeout_seconds)
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


async def heal_node_failure(
    stage: str,
    state: ApplyState,
    error: str,
    traceback_text: str,
    *,
    node_fn: NodeFn,
    reopen: ReopenMode = "job",
    settings: Settings | None = None,
    progress=None,
    bug_root: Path | None = None,
    capture_fn=None,
    record_fn=None,
    close_fn=None,
    repair_fn=None,
    reopen_fn=None,
    reopen_results_fn=None,
) -> ApplyState:
    """Record, close, repair/test, reopen, and retry ``node_fn`` (bounded)."""
    settings = settings or load_settings()
    root = bug_root or PROJECT_ROOT
    notify = progress or print
    capture_fn = capture_fn or capture_failure
    record_fn = record_fn or (lambda captured: record_failure(captured, root=root))
    close_fn = close_fn or close_run_force
    repair_fn = repair_fn or run_repair_and_test
    reopen_job_fn = reopen_fn or reopen_same_job
    reopen_results_fn = reopen_results_fn or _reopen_results

    outcome = SelfHealingOutcome(enabled=bool(settings.self_healing.enabled))
    max_attempts = max(0, settings.self_healing.max_repair_attempts)
    log = [f"self-heal({stage}): caught crash - {error}"]
    errors = [f"{stage}: {error}"]
    working: ApplyState = dict(state)
    target = job_target_from_state(state)

    if not settings.self_healing.enabled or max_attempts == 0:
        outcome.stop_reason = "self-healing is disabled"
        log.append(f"self-heal({stage}): {outcome.stop_reason}")
        return _failed_result(stage, working, outcome, errors, log)

    current_error = error
    current_tb = traceback_text
    run_id = working.get("browser_run_id")
    last_attempt = 0

    for attempt in range(1, max_attempts + 1):
        last_attempt = attempt
        try:
            captured = await capture_fn(
                run_id,
                settings,
                stage=stage,
                error=current_error,
                task4=working.get("task4"),
                target=target,
                traceback_text=current_tb,
            )
        except Exception as exc:  # noqa: BLE001 - never lose the original crash
            outcome.stop_reason = f"evidence capture failed: {exc}"
            errors.append(f"self-heal({stage}): {outcome.stop_reason}")
            log.append(f"self-heal({stage}): evidence capture failed: {exc}")
            break

        target = _target_with_live_url(target, captured.evidence.page_url)
        try:
            record = record_fn(captured)
        except Exception as exc:  # noqa: BLE001 - logging must not block recovery
            record = FailureRecord(
                fingerprint=captured.fingerprint,
                category=captured.category,
                bundle_dir=captured.bundle_dir,
                symptom=captured.symptom,
                evidence=captured.evidence,
            )
            log.append(f"self-heal({stage}): bug log write failed: {exc}")
        outcome.failures.append(record)
        outcome.last_bundle = captured.bundle_dir
        if record.bug_id and record.bug_id not in outcome.bug_ids:
            outcome.bug_ids.append(record.bug_id)
        log.append(
            f"self-heal({stage}): attempt {attempt}/{max_attempts}: "
            f"{captured.category}; bug={record.bug_id or '(unlogged)'}; "
            f"bundle={captured.bundle_dir}"
        )
        notify(
            f"self-heal({stage}): recorded {record.bug_id or 'the failure'} "
            f"({captured.category}); closing the browser..."
        )
        closed, close_detail = await close_fn(run_id, settings)
        outcome.attempt_log.append(
            HealingAttempt(
                attempt=attempt,
                action="close_browser",
                success=closed,
                detail=close_detail,
            )
        )
        log.append(f"self-heal({stage}): close browser success={closed} ({close_detail})")
        if not closed:
            outcome.stop_reason = f"could not close the failed browser: {close_detail}"
            errors.append(f"self-heal({stage}): {outcome.stop_reason}")
            break
        working.pop("browser_run_id", None)

        repaired, repair_detail = await repair_fn(
            settings, captured, record, notify
        )
        outcome.attempt_log.append(
            HealingAttempt(
                attempt=attempt,
                action="repair_and_test",
                success=repaired,
                detail=repair_detail,
            )
        )
        log.append(f"self-heal({stage}): repair/test: {repair_detail}")
        if not repaired:
            outcome.stop_reason = repair_detail
            errors.append(f"self-heal({stage}): {repair_detail}")
            break

        if (settings.self_healing.repair_command or "").strip():
            reload_failures = reload_runtime_modules()
            outcome.attempt_log.append(
                HealingAttempt(
                    attempt=attempt,
                    action="reload_runtime",
                    success=not reload_failures,
                    detail="; ".join(reload_failures) or "browser/fill modules reloaded",
                )
            )
            if reload_failures:
                outcome.stop_reason = (
                    "repaired code could not be reloaded safely: "
                    + "; ".join(reload_failures)
                )
                errors.append(f"self-heal({stage}): {outcome.stop_reason}")
                break

        if reopen == "job":
            reopened = await reopen_job_fn(target, settings, notify)
        elif reopen == "results":
            reopened = await reopen_results_fn(target, settings, notify, captured)
        else:
            reopened = ReopenResult(run_id="", task2=None)
            # No browser reopen is needed: the node launches its own session.
            reopened.reason = "no browser reopen needed"
            # ``ReopenResult.opened`` requires a run id, so retry without one.
            reopened.run_id = ""

        if reopen is not None and not reopened.opened:
            outcome.stop_reason = reopened.reason or "the failed step could not be reopened"
            errors.append(f"self-heal({stage}): {outcome.stop_reason}")
            outcome.attempt_log.append(
                HealingAttempt(
                    attempt=attempt,
                    action="reopen",
                    success=False,
                    detail=outcome.stop_reason,
                )
            )
            break

        if reopened.run_id:
            working["browser_run_id"] = reopened.run_id
            run_id = reopened.run_id
            if reopened.task2 is not None:
                working["task2"] = reopened.task2
            if reopened.description is not None:
                working["job_description"] = reopened.description
            working.pop("errors", None)
        outcome.attempt_log.append(
            HealingAttempt(
                attempt=attempt,
                action="reopen",
                success=True,
                detail=reopened.reason or f"run={reopened.run_id}",
            )
        )
        log.append(
            f"self-heal({stage}): retrying {stage} "
            f"(run={run_id or '(none)'})..."
        )
        notify(f"self-heal({stage}): retrying the failed step...")

        try:
            update = await _call_node(node_fn, working)
        except Exception as exc:  # noqa: BLE001 - bounded retry, record next attempt
            current_error = str(exc)
            current_tb = traceback.format_exc()
            run_id = working.get("browser_run_id")
            log.append(f"self-heal({stage}): retry {attempt} crashed: {exc}")
            continue

        outcome.recovered = True
        outcome.attempts = attempt
        outcome.stop_reason = ""
        mark_fixed(
            outcome.failures,
            settings,
            root=root,
            evidence=(
                f"bundle `{outcome.last_bundle}`; attempts={attempt}; "
                f"run=`{run_id or '(none)'}`"
            ),
        )
        notify(f"self-heal({stage}): recovered - resumed the failed step.")
        return _merge_recovered(update, working, outcome, stage, log)

    outcome.attempts = last_attempt
    if not outcome.stop_reason:
        outcome.stop_reason = (
            f"still failing after {outcome.attempts} recovery attempt(s)"
        )
    outcome.exhausted = outcome.attempts >= max_attempts
    if outcome.exhausted:
        mark_exhausted(outcome.failures, root, outcome.attempts)
    errors.append(f"self-heal({stage}): {outcome.stop_reason}")
    log.append(f"self-heal({stage}): stopping - {outcome.stop_reason}")
    notify(f"self-heal({stage}): stopping - {outcome.stop_reason}. Evidence preserved.")
    return _failed_result(stage, working, outcome, errors, log)


def guard_node(name: str, node_fn: NodeFn, *, reopen: ReopenMode = "job") -> NodeFn:
    """Wrap ``node_fn`` so any uncaught exception enters the self-healing loop."""

    async def guarded(state: ApplyState) -> ApplyState:
        if state.get("dry_run", True):
            return await _call_node(node_fn, state)
        try:
            return await _call_node(node_fn, state)
        except Exception as exc:  # noqa: BLE001 - self-heal instead of ending the run
            traceback_text = traceback.format_exc()
            return await heal_node_failure(
                name,
                state,
                str(exc),
                traceback_text,
                node_fn=node_fn,
                reopen=reopen,
                progress=_reporter(state.get("browser_run_id")),
            )

    guarded.__name__ = getattr(node_fn, "__name__", name)
    guarded.__doc__ = getattr(node_fn, "__doc__", None)
    return guarded


__all__ = ["guard_node", "heal_node_failure"]
