"""Task 4: fill the open Easy Apply form and attach the chosen resume.

The live browser session (kept open by the ``browse`` node and registered under
``state['browser_run_id']``) is used here to fill the same Easy Apply modal. The
session is **not** closed here — the ``cleanup`` node owns that, so a failed fill
can still be screenshotted first. The application is never submitted.

Task 5 runs inside this fill (see :func:`fill_application`): unknown questions
pause on a browser banner for the human and their answers are remembered.
"""

from __future__ import annotations

from src.state import ApplyState


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

    from src.tools.browser import fill_application  # lazy: needs the `browser` extra

    try:
        from src.tools.browser import get_reporter  # lazy: keeps this node light

        progress = get_reporter(run_id) or print
        outcome, task5 = await fill_application(
            run_id, task3.selected_path, progress=progress
        )
    except Exception as exc:  # noqa: BLE001 - surface any fill failure
        return {
            "status": "failed",
            "errors": [f"fill: {exc}"],
            "log": ["fill: form filling failed"],
        }

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
    decisions = [
        f"{field.question!r}->{field.value!r} "
        f"({'derived' if field.derived else 'matched'}"
        f"{', sources=' + repr(field.source_keys) if field.source_keys else ''}; "
        f"key={field.matched_key!r}, {field.question_type or 'question'}: "
        f"{field.rationale or 'no rationale'})"
        for field in outcome.fields
        if field.answered_by == "llm"
    ]
    if decisions:
        log.append("fill(task4.1/task10): LLM chose " + "; ".join(decisions))
    if task5.notes:
        log.append(f"fill(task5): {task5.notes}")
    if outcome.notes:
        log.append(f"fill: {outcome.notes}")

    update: ApplyState = {"task4": outcome, "task5": task5, "status": "filled", "log": log}

    errors: list[str] = []
    if not outcome.form_open:
        errors.append("fill: Easy Apply form was not found")
    elif not outcome.resume_attached:
        errors.append("fill: resume was not attached")
    else:
        required_unknown = [
            field for field in outcome.fields if field.required and not field.known
        ]
        required_unfilled = [
            field
            for field in outcome.fields
            if field.required and field.known and not field.filled
        ]
        if required_unknown:
            errors.append(
                "fill: required questions are unanswered: "
                + "; ".join(field.question or field.name for field in required_unknown)
            )
        if required_unfilled:
            errors.append(
                "fill: required fields were not filled: "
                + "; ".join(field.question or field.name for field in required_unfilled)
            )
    if outcome.submitted:
        errors.append("fill: Submit was clicked (must never happen)")
    if errors:
        update["errors"] = errors
    return update


__all__ = ["fill"]
