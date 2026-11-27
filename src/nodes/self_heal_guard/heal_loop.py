"""The bounded record/close/repair/reopen/retry loop for a crashed node (Task 11)."""

from __future__ import annotations

import traceback
from pathlib import Path

from src.configuration import PROJECT_ROOT, Settings, load_settings
from src.nodes.self_heal_guard.crash_record import record_node_crash, remember_recovered
from src.nodes.self_heal_guard.helpers import (
    NodeFn,
    ReopenMode,
    _call_node,
    _failed_result,
    _merge_recovered,
    _reopen_results,
    _target_with_live_url,
)
from src.state import ApplyState
from src.tools.self_healing.buglog import mark_exhausted, mark_fixed, record_failure
from src.tools.self_healing.capture import capture_failure
from src.tools.self_healing.models import FailureRecord, HealingAttempt, SelfHealingOutcome
from src.tools.self_healing.recovery import (
    ReopenResult,
    close_run_force,
    job_target_from_state,
    reload_runtime_modules,
    reopen_same_job,
    run_repair_and_test,
)


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
    exc: BaseException | None = None,
) -> ApplyState:
    """Record, close, repair/test, reopen, and retry ``node_fn`` (bounded).

    Task 33: when the loop cannot recover (disabled, capture failed, or
    exhausted) one terminal crash bundle is written before returning.
    """
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
        result = _failed_result(stage, working, outcome, errors, log)
        await record_node_crash(
            stage, working, result, outcome,
            exc=exc, error=error, traceback_text=traceback_text,
        )
        return result

    current_error = error
    current_tb = traceback_text
    crash_extra: dict = {}
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
        except Exception as capture_exc:  # noqa: BLE001 - never lose the original crash
            outcome.stop_reason = f"evidence capture failed: {capture_exc}"
            crash_extra["capture_error"] = f"{type(capture_exc).__name__}: {capture_exc}"
            errors.append(f"self-heal({stage}): {outcome.stop_reason}")
            log.append(f"self-heal({stage}): evidence capture failed: {capture_exc}")
            break

        target = _target_with_live_url(target, captured.evidence.page_url)
        try:
            record = record_fn(captured)
        except Exception as log_exc:  # noqa: BLE001 - logging must not block recovery
            record = FailureRecord(
                fingerprint=captured.fingerprint,
                category=captured.category,
                bundle_dir=captured.bundle_dir,
                symptom=captured.symptom,
                evidence=captured.evidence,
            )
            log.append(f"self-heal({stage}): bug log write failed: {log_exc}")
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
        except Exception as retry_exc:  # noqa: BLE001 - bounded retry, record next attempt
            current_error = str(retry_exc)
            current_tb = traceback.format_exc()
            crash_extra["last_error"] = current_error
            crash_extra["last_traceback"] = current_tb
            run_id = working.get("browser_run_id")
            log.append(f"self-heal({stage}): retry {attempt} crashed: {retry_exc}")
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
        merged = _merge_recovered(update, working, outcome, stage, log)
        remember_recovered(stage, working, merged)
        return merged

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
    result = _failed_result(stage, working, outcome, errors, log)
    await record_node_crash(
        stage, working, result, outcome,
        exc=exc, error=error, traceback_text=traceback_text, extra=crash_extra,
    )
    return result


__all__ = ["heal_node_failure"]
