"""Bounded self-healing loop for a failed Easy Apply fill.

The loop is deliberately conservative:

1. Capture evidence and record the bug while the failed form is still open.
2. Close the browser run cleanly and verify its profile lock is gone.
3. Run an optional repair command and test command (both configured by the user).
4. Reopen the **same** job in a fresh browser, re-attach the resume, and re-fill.
5. Stop after the configured attempt cap; never keep patching or retrying forever.

If no repair command is configured, the loop performs runtime recovery only: it
restarts the browser and retries the same job. It never modifies source code at
runtime; an external agent/developer can use the recorded bundle to fix the root
cause and then run the loop again.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.configuration import PROJECT_ROOT, Settings, load_settings
from src.state import (
    JobAnswerContext,
    JobDescription,
    Task2Outcome,
    Task4Outcome,
    Task5Outcome,
)
from src.tools.self_healing.buglog import mark_exhausted, mark_fixed, record_failure
from src.tools.self_healing.capture import capture_failure, install_console_capture
from src.tools.self_healing.fingerprint import (
    classify_failure,
    fill_failure_reason,
    is_recoverable,
    recovery_reason,
)
from src.tools.self_healing.models import (
    CapturedFailure,
    FailureRecord,
    HealingAttempt,
    JobTarget,
    SelfHealingOutcome,
)
from src.tools.self_healing.recovery import (
    CommandFn,
    ReopenResult,
    close_run_force,
    job_target_from_state,
    reload_runtime_modules,
    reopen_same_job,
    run_repair_and_test,
)

FillFn = Callable[..., Awaitable[tuple[Task4Outcome, Task5Outcome]]]
ReopenFn = Callable[[JobTarget, Settings, Any], Awaitable[ReopenResult]]
CaptureFn = Callable[..., Awaitable[CapturedFailure]]
RecordFn = Callable[[CapturedFailure], FailureRecord]
CloseFn = Callable[[str | None, Settings], Awaitable[tuple[bool, str]]]

# Kept importable from this module for callers/tests that used the loop's name.
failure_reason = fill_failure_reason


@dataclass
class HealResult:
    """The result of healing one failed fill."""

    recovered: bool = False
    run_id: str = ""
    task4: Task4Outcome | None = None
    task5: Task5Outcome | None = None
    task2: Task2Outcome | None = None
    description: JobDescription | None = None
    outcome: SelfHealingOutcome = field(default_factory=SelfHealingOutcome)
    errors: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


def _target_with_live_url(target: JobTarget | None, page_url: str) -> JobTarget:
    """Point the reopen at the exact page the failed run was on.

    The browser's address bar holds the main URL, for example
    ``https://www.linkedin.com/jobs/search-results/?currentJobId=...``. Navigating
    straight back to it reopens the same job's details pane and Easy Apply button,
    which is more reliable than a reconstructed ``/jobs/view/<id>`` URL or searching
    again. Non-LinkedIn-jobs URLs (a login or interstitial) fall back to the recorded
    target URL so recovery never wanders off.
    """
    resolved = target.model_copy() if target is not None else JobTarget()
    live = (page_url or "").strip()
    if live.startswith(("http://", "https://")) and "linkedin.com/jobs" in live.lower():
        resolved.url = live
    return resolved


def _merge_task5(first: Task5Outcome, second: Task5Outcome) -> Task5Outcome:
    """Combine Task 5 counts when the same fill is retried."""
    answered = list(first.answered_questions)
    for question in second.answered_questions:
        if question not in answered:
            answered.append(question)
    notes = "; ".join(note for note in (first.notes, second.notes) if note)
    return Task5Outcome(
        enabled=first.enabled or second.enabled,
        asked=first.asked + second.asked,
        answered=first.answered + second.answered,
        skipped=first.skipped + second.skipped,
        timed_out=first.timed_out + second.timed_out,
        answered_questions=answered,
        notes=notes,
    )


def _default_capture():
    return capture_failure


def _default_record(root: Path):
    def record(captured: CapturedFailure) -> FailureRecord:
        return record_failure(captured, root=root)

    return record


async def _default_fill(
    run_id: str,
    resume_path: str,
    settings: Settings,
    progress,
    context: JobAnswerContext | None = None,
) -> tuple[Task4Outcome, Task5Outcome]:
    from src.tools.browser import fill_application

    return await fill_application(
        run_id, resume_path, settings=settings, progress=progress, context=context
    )


async def heal_fill_failure(
    *,
    run_id: str | None,
    task4: Task4Outcome | None,
    task5: Task5Outcome | None,
    settings: Settings | None = None,
    progress=None,
    target: JobTarget | None = None,
    resume_path: str = "",
    task2: Task2Outcome | None = None,
    description: JobDescription | None = None,
    error: str = "",
    traceback_text: str = "",
    context: JobAnswerContext | None = None,
    bug_root: Path | None = None,
    fill_fn: FillFn | None = None,
    reopen_fn: ReopenFn | None = None,
    capture_fn: CaptureFn | None = None,
    record_fn: RecordFn | None = None,
    close_fn: CloseFn | None = None,
    command_fn: CommandFn | None = None,
) -> HealResult:
    """Record, close, optionally repair/test, reopen the same job, and re-fill."""
    settings = settings or load_settings()
    notify = progress or (lambda _message: None)
    root = bug_root or PROJECT_ROOT
    fill_fn = fill_fn or _default_fill
    reopen_fn = reopen_fn or reopen_same_job
    capture_fn = capture_fn or _default_capture()
    record_fn = record_fn or _default_record(root)
    close_fn = close_fn or close_run_force

    outcome = SelfHealingOutcome(enabled=True)
    log: list[str] = []
    errors: list[str] = []
    current_run_id = run_id or ""
    current_task4 = task4
    current_task2 = task2
    current_description = description
    total_task5 = task5 or Task5Outcome()
    max_attempts = max(0, settings.self_healing.max_repair_attempts)
    if max_attempts == 0:
        return HealResult(
            recovered=False,
            run_id=current_run_id,
            task4=current_task4,
            task5=total_task5,
            outcome=SelfHealingOutcome(enabled=True, stop_reason="self-healing is disabled"),
            errors=["self-heal: self-healing is disabled"],
            log=["self-heal: disabled by AUTOJOB_SELF_HEAL_MAX_ATTEMPTS=0"],
        )

    for attempt in range(1, max_attempts + 1):
        reason = error or failure_reason(current_task4)
        category = classify_failure(error, current_task4)
        if not is_recoverable(category, current_task4):
            outcome.stop_reason = recovery_reason(category, current_task4)
            errors.append(f"self-heal: {outcome.stop_reason}")
            log.append(f"self-heal: not reopening - {outcome.stop_reason}")
            break

        try:
            captured = await capture_fn(
                current_run_id,
                settings,
                stage="fill",
                error=reason,
                task4=current_task4,
                target=target,
                traceback_text=traceback_text,
            )
        except Exception as exc:  # noqa: BLE001 - never lose the original failure
            outcome.stop_reason = f"evidence capture failed: {exc}"
            errors.append(f"self-heal: {outcome.stop_reason}")
            log.append(f"self-heal: evidence capture failed: {exc}")
            break

        # Reopen the exact address-bar URL captured at the crash (for example the
        # search-results page with ``currentJobId``), not a reconstructed job URL.
        target = _target_with_live_url(target, captured.evidence.page_url)
        if target.url:
            notify(f"self-heal: will reopen {target.url}")

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
            log.append(f"self-heal: bug log write failed: {exc}")
        outcome.failures.append(record)
        outcome.last_bundle = captured.bundle_dir
        if record.bug_id and record.bug_id not in outcome.bug_ids:
            outcome.bug_ids.append(record.bug_id)
        log.append(
            f"self-heal: attempt {attempt}/{max_attempts}: {captured.category}; "
            f"bug={record.bug_id or '(unlogged)'}; bundle={captured.bundle_dir}"
        )
        notify(
            f"self-heal: recorded {record.bug_id or 'the failure'} "
            f"({captured.category}); closing the browser..."
        )
        with contextlib.suppress(Exception):
            from src.tools.linkedin_status_overlay import emit_step

            emit_step(notify, "Self-healing - recorded the failure; reopening the same job...")

        closed, close_detail = await close_fn(current_run_id, settings)
        outcome.attempt_log.append(
            HealingAttempt(
                attempt=attempt,
                action="close_browser",
                success=closed,
                detail=close_detail,
            )
        )
        log.append(f"self-heal: close browser success={closed} ({close_detail})")
        if not closed:
            outcome.stop_reason = f"could not close the failed browser: {close_detail}"
            errors.append(f"self-heal: {outcome.stop_reason}")
            break

        repaired, repair_detail = await run_repair_and_test(
            settings, captured, record, notify, command_fn
        )
        outcome.attempt_log.append(
            HealingAttempt(
                attempt=attempt,
                action="repair_and_test",
                success=repaired,
                detail=repair_detail,
            )
        )
        log.append(f"self-heal: repair/test: {repair_detail}")
        if not repaired:
            outcome.stop_reason = repair_detail
            errors.append(f"self-heal: {repair_detail}")
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
                outcome.stop_reason = "repaired code could not be reloaded safely: " + "; ".join(
                    reload_failures
                )
                errors.append(f"self-heal: {outcome.stop_reason}")
                break
            log.append("self-heal: reloaded the repaired browser/fill modules.")

        reopened = await reopen_fn(target or JobTarget(), settings, notify)
        outcome.attempt_log.append(
            HealingAttempt(
                attempt=attempt,
                action="reopen_same_job",
                success=reopened.opened,
                detail=reopened.reason or f"run={reopened.run_id}",
            )
        )
        if not reopened.opened:
            outcome.stop_reason = reopened.reason or "the same job did not reopen"
            errors.append(f"self-heal: {outcome.stop_reason}")
            log.append(f"self-heal: reopen failed - {outcome.stop_reason}")
            break
        current_run_id = reopened.run_id
        outcome.attempts = attempt
        current_task2 = reopened.task2 or current_task2
        current_description = reopened.description or current_description
        with contextlib.suppress(Exception):
            from src.tools.browser import get_reporter

            notify = get_reporter(current_run_id) or notify
        await install_console_capture(current_run_id)
        log.append(f"self-heal: reopened the same job (run={current_run_id}); retrying fill...")
        notify("self-heal: reopened the same job; retrying the fill...")

        try:
            fill_kwargs: dict = {
                "settings": settings,
                "progress": notify,
            }
            if context is not None:
                # Task 12: rebuild the job context from the reopened job's
                # description, keeping the same selected resume for this job.
                from src.tools.job_context import build_job_context

                fill_kwargs["context"] = build_job_context(
                    current_description,
                    resume_path,
                    settings.resume_descriptions_file,
                )
            current_task4, retry_task5 = await fill_fn(
                current_run_id, resume_path, **fill_kwargs
            )
        except Exception as exc:  # noqa: BLE001 - record and continue the bounded loop
            current_task4 = Task4Outcome(
                resume_path=resume_path,
                notes=f"fill raised: {exc}",
            )
            retry_task5 = Task5Outcome()
            log.append(f"self-heal: retry fill raised: {exc}")
        total_task5 = _merge_task5(total_task5, retry_task5)
        reason = failure_reason(current_task4)
        outcome.attempt_log.append(
            HealingAttempt(
                attempt=attempt,
                action="refill",
                success=not reason,
                detail=reason or "fill completed",
            )
        )
        if not reason:
            outcome.recovered = True
            outcome.stop_reason = ""
            evidence = f"bundle `{outcome.last_bundle}`; attempts={attempt}; run=`{current_run_id}`"
            mark_fixed(outcome.failures, settings, root=root, evidence=evidence)
            log.append(f"self-heal: recovered and re-filled the same job in {attempt} attempt(s).")
            notify("self-heal: recovered - the same job is filled again.")
            return HealResult(
                recovered=True,
                run_id=current_run_id,
                task4=current_task4,
                task5=total_task5,
                task2=current_task2,
                description=current_description,
                outcome=outcome,
                log=log,
            )
        log.append(f"self-heal: retry {attempt} still failed - {reason}")
        error = reason

    if not outcome.recovered:
        outcome.exhausted = outcome.attempts >= max_attempts
        outcome.stop_reason = outcome.stop_reason or (
            f"still failing after {outcome.attempts} recovery attempt(s)"
        )
        if outcome.exhausted:
            mark_exhausted(outcome.failures, root, outcome.attempts)
        errors.append(f"self-heal: {outcome.stop_reason}")
        log.append(f"self-heal: stopping - {outcome.stop_reason}")
        notify(f"self-heal: stopping - {outcome.stop_reason}. Evidence preserved.")
    return HealResult(
        recovered=False,
        run_id=current_run_id,
        task4=current_task4,
        task5=total_task5,
        task2=current_task2,
        description=current_description,
        outcome=outcome,
        errors=errors,
        log=log,
    )


__all__ = ["HealResult", "failure_reason", "heal_fill_failure", "job_target_from_state"]
