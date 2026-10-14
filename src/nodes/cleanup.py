"""Close the live browser session before the run is verified.

Tasks 2-4 share one session kept open by the ``browse`` node. Whatever path the
run takes (success, a matching failure, or a skipped fill), this node closes it,
so no Chromium window is left behind — **except** when Task 4 stopped at the
terminal step (only **Submit application** remains) and the **Task 8 loop is
off**. In that case the browser is left open for the human to review and submit
the application manually, and this node waits until the human closes the window
(or a timeout elapses) before the run finishes.

When the Task 8 loop ran, the per-job human-submit wait already happened in
``await_submit``; this node then just closes the session once (the loop may have
moved past the last confirmation, so there is nothing left to wait on).
"""

from __future__ import annotations

from src.state import ApplyState

_RELEASE_LOG = {
    "closed": "cleanup: browser session closed",
    "human": "cleanup: browser left open for the human; closed by the human",
    "timeout": "cleanup: browser left open for the human; wait timed out, session closed",
}


async def cleanup(state: ApplyState) -> ApplyState:
    """Close the browser, unless Task 4 stopped at the last step for the human."""
    run_id = state.get("browser_run_id")
    if not run_id:
        return {}

    from src.tools.browser import close_run, release_run  # lazy: needs the `browser` extra

    if state.get("task8") is not None:
        # Task 8's loop already waited for the human on each job; close once.
        try:
            await close_run(run_id)
        except Exception as exc:  # noqa: BLE001 - never let cleanup fail the run
            return {"errors": [f"cleanup: {exc}"], "log": ["cleanup: browser release failed"]}
        return {"log": ["cleanup: browser session closed (Task 8 loop finished)"]}

    try:
        released = await release_run(run_id, state.get("task4"), progress=print)
    except Exception as exc:  # noqa: BLE001 - never let cleanup fail the run
        return {"errors": [f"cleanup: {exc}"], "log": ["cleanup: browser release failed"]}
    return {"log": [_RELEASE_LOG.get(released, "cleanup: browser session closed")]}


__all__ = ["cleanup"]
