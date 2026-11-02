"""Task 4: fill the open Easy Apply form and attach the chosen resume.

The live browser session (kept open by the ``browse`` node and registered under
``state['browser_run_id']``) is used here to fill the same Easy Apply modal. The
session is **not** closed here unless Task 11's self-healing loop has to restart
it; the ``cleanup`` node owns the final release, so a failed fill can still be
screenshotted first. The application is never submitted.

Task 5 runs inside this fill (see :func:`fill_application`): unknown questions
pause on a browser banner for the human and their answers are remembered.
"""

from __future__ import annotations

import contextlib
import traceback

from src.configuration import load_settings
from src.state import ApplyState, FormField, Task4Outcome, Task5Outcome


def _fill_errors(outcome: Task4Outcome) -> list[str]:
    """Turn a Task 4 outcome into the errors that make the fill fail.

    Delegates to :func:`~src.tools.self_healing.fingerprint.fill_failure_reason`
    so the fill node, the self-healing loop, and ``verify`` apply the **same**
    success rule. A stopped walk (it never reached the final review step) must be
    an error, otherwise a crashed fill looks like a success and self-healing never
    fires (BUG-050).
    """
    from src.tools.self_healing.fingerprint import fill_failure_reason

    reason = fill_failure_reason(outcome)
    if not reason:
        return []
    errors = [reason]
    # ``fill_failure_reason`` reports the first blocker; also name required fields
    # that are known but failed to fill so one message lists every blocker.
    unfilled = [
        field for field in outcome.fields if field.required and field.known and not field.filled
    ]
    if unfilled:
        extra = "fill: required fields were not filled: " + "; ".join(
            field.question or field.name for field in unfilled
        )
        if extra not in errors:
            errors.append(extra)
    return errors


def _decision_line(field: FormField) -> str:
    """One LLM decision for the audit log, including Task 12 provenance."""
    if field.answer_source:
        evidence = "; ".join(
            snippet if len(snippet) <= 120 else snippet[:117] + "..."
            for snippet in field.context_evidence
            if snippet
        )
        return (
            f"{field.question!r}->{field.value!r} "
            f"(job-specific, source={field.answer_source}, evidence={evidence!r}; "
            f"{field.rationale or 'no rationale'})"
        )
    return (
        f"{field.question!r}->{field.value!r} "
        f"({'derived' if field.derived else 'matched'}"
        f"{', sources=' + repr(field.source_keys) if field.source_keys else ''}; "
        f"key={field.matched_key!r}, {field.question_type or 'question'}: "
        f"{field.rationale or 'no rationale'})"
    )


def _fill_log(outcome: Task4Outcome, task5: Task5Outcome) -> list[str]:
    """Build the audit log for one fill (kept compatible with earlier runs)."""
    log = [
        "fill: "
        f"form_open={outcome.form_open} "
        f"fields={outcome.fields_enumerated} "
        f"known={outcome.known_fields} "
        f"filled={outcome.filled_fields} "
        f"resume={outcome.resume_selection or 'none'} "
        f"submitted={outcome.submitted}",
        "fill(task5): "
        f"asked={task5.asked} answered={task5.answered} "
        f"skipped={task5.skipped} timed_out={task5.timed_out}",
    ]
    if outcome.unknown_fields:
        log.append(f"fill: unknown (left for Task 5): {outcome.unknown_fields}")
    unfilled = [field for field in outcome.fields if field.known and not field.filled]
    if unfilled:
        log.append(
            "fill: known but not filled: "
            + "; ".join(
                f"{field.question or field.name!r}"
                + (f" ({field.error})" if field.error else "")
                + (" [required]" if field.required else "")
                for field in unfilled
            )
        )
    if outcome.job_context.sources or outcome.job_context.errors:
        context = outcome.job_context
        log.append(
            "fill(task12): "
            f"job={context.job_title or '(untitled)'!r} company={context.company or '(none)'!r} "
            f"resume={context.resume_path or '(none)'!r} "
            f"job_chars={context.job_chars} resume_chars={context.resume_chars} "
            f"profile={context.profile_available} sources={context.sources}"
            + (f" errors={context.errors}" if context.errors else "")
        )
    decisions = [_decision_line(field) for field in outcome.fields if field.answered_by == "llm"]
    if decisions:
        log.append("fill(task4.1/task10/task12): LLM chose " + "; ".join(decisions))
    if task5.notes:
        log.append(f"fill(task5): {task5.notes}")
    if outcome.notes:
        log.append(f"fill: {outcome.notes}")
    return log


def _should_heal(outcome: Task4Outcome, error: str, settings) -> tuple[bool, str]:
    """Decide whether the failure is structural enough to retry in a new browser."""
    from src.tools.self_healing.fingerprint import classify_failure, is_recoverable

    if not settings.self_healing.enabled:
        return False, "self-healing is disabled"
    if settings.self_healing.max_repair_attempts <= 0:
        return False, "the self-healing attempt cap is zero"
    if outcome.submitted:
        return False, "Submit was clicked; never retrying that automatically"
    category = classify_failure(error, outcome)
    return is_recoverable(category, outcome), category


async def fill(state: ApplyState) -> ApplyState:
    """Fill known fields and attach the Task 3 resume; never submit."""
    if state.get("dry_run", True):
        return {"status": "filled", "log": ["fill: dry-run, form not filled"]}

    run_id = state.get("browser_run_id")
    task3 = state.get("task3")
    if not run_id or task3 is None or not task3.selected_path:
        return {
            "status": "failed",
            "errors": ["fill: no open browser session or selected resume"],
            "log": ["fill: form filling skipped"],
        }

    settings = load_settings()
    from src.tools.browser import fill_application, get_reporter  # lazy: browser extra
    from src.tools.job_context import build_job_context

    # Task 12: build a fresh context for THIS job (never reuse another job's). A
    # read failure only records an error on the context; the fill still runs.
    description = state.get("job_description")
    if description is None or not getattr(description, "is_read", False):
        description = task3.job_description
    context = build_job_context(description, task3.selected_path, settings.resume_descriptions_file)

    progress = get_reporter(run_id) or print
    if settings.self_healing.enabled:
        with contextlib.suppress(Exception):
            from src.tools.self_healing.capture import install_console_capture

            await install_console_capture(run_id)

    error = ""
    traceback_text = ""
    outcome = Task4Outcome(resume_path=task3.selected_path, job_context=context.audit())
    task5 = Task5Outcome()
    try:
        outcome, task5 = await fill_application(
            run_id,
            task3.selected_path,
            settings=settings,
            progress=progress,
            context=context,
        )
    except Exception as exc:  # noqa: BLE001 - surface any fill failure
        error = str(exc)
        traceback_text = traceback.format_exc()
        outcome = Task4Outcome(
            resume_path=task3.selected_path,
            job_context=context.audit(),
            notes=f"fill raised: {exc}",
        )
    outcome.job_context = context.audit()
    update: ApplyState = {
        "task4": outcome,
        "task5": task5,
        "job_context": context,
        "status": "filled",
        "log": _fill_log(outcome, task5),
    }
    log = update["log"]
    errors = _fill_errors(outcome)
    if error:
        errors.insert(0, f"fill: {error}")

    should_heal, category = _should_heal(outcome, error, settings)
    if errors and should_heal:
        from src.tools.self_healing.loop import (
            HealResult,
            heal_fill_failure,
            job_target_from_state,
        )

        try:
            healing = await heal_fill_failure(
                run_id=run_id,
                task4=outcome,
                task5=task5,
                settings=settings,
                progress=progress,
                target=job_target_from_state(state),
                resume_path=str(task3.selected_path),
                task2=state.get("task2"),
                description=description,
                error=error,
                traceback_text=traceback_text,
                context=context,
            )
        except Exception as exc:  # noqa: BLE001 - healing must not crash the run
            healing = HealResult(
                recovered=False,
                errors=[f"self-heal: loop failed: {exc}"],
                log=[f"fill(self-heal): loop failed: {exc}"],
            )
        update["self_healing"] = healing.outcome
        log.extend(healing.log)
        if healing.task4 is not None:
            outcome = healing.task4
            task5 = healing.task5 or task5
            update["task4"] = outcome
            update["task5"] = task5
        if healing.run_id:
            update["browser_run_id"] = healing.run_id
        if healing.task2 is not None:
            previous_task2 = state.get("task2")
            if healing.task2.job_index is None and previous_task2 is not None:
                healing.task2.job_index = previous_task2.job_index
            update["task2"] = healing.task2
        if healing.description is not None:
            update["job_description"] = healing.description
            # Task 12: rebuild for the same job after the heal, using the
            # description the reopened page produced (never the previous job's).
            context = build_job_context(
                healing.description, task3.selected_path, settings.resume_descriptions_file
            )
            update["job_context"] = context
            outcome.job_context = context.audit()
        if healing.recovered:
            errors = _fill_errors(outcome)
            log.append(
                "fill(self-heal): recovered the same job after "
                f"{healing.outcome.attempts} attempt(s)"
            )
        else:
            errors.extend(error for error in healing.errors if error not in errors)
    elif errors and not should_heal:
        log.append(f"fill: not auto-recovering - {category}")

    if errors:
        update["errors"] = errors
    return update


__all__ = ["fill"]
