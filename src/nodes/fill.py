"""Task 4: fill the open Easy Apply form and attach the chosen resume.

The live browser session (kept open by the ``browse`` node and registered under
``state['browser_run_id']``) is used here to fill the same Easy Apply modal. The
session is **not** closed here — the ``cleanup`` node owns that, so a failed fill
can still be screenshotted first. The application is never submitted.
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
        outcome = await fill_application(run_id, task3.selected_path, progress=print)
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
        f"submitted={outcome.submitted}"
    ]
    if outcome.unknown_fields:
        log.append(f"fill: unknown (left for Task 5): {outcome.unknown_fields}")
    if outcome.notes:
        log.append(f"fill: {outcome.notes}")

    update: ApplyState = {"task4": outcome, "status": "filled", "log": log}

    errors: list[str] = []
    if not outcome.form_open:
        errors.append("fill: Easy Apply form was not found")
    elif not outcome.resume_attached:
        errors.append("fill: resume was not attached")
    elif outcome.filled_fields != outcome.known_fields:
        errors.append("fill: some known fields were not filled")
    if outcome.submitted:
        errors.append("fill: Submit was clicked (must never happen)")
    if errors:
        update["errors"] = errors
    return update


__all__ = ["fill"]
