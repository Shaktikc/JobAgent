"""Release the live browser session before the run is verified.

Tasks 2-4 share one session kept open by the ``browse`` node. The agent **never
closes the browser**: on every path (success, a matching failure, or a skipped
fill) this node only releases the run's handle and detaches from the CDP link,
leaving the Chromium window open so a failure can be inspected and the human can
keep driving it. When Task 4 stopped at the terminal step (only **Submit
application** remains) it waits for the human to close the window (or a timeout
elapses) first; the window is left open either way.

When the Task 8 loop ran, the per-job human-submit wait already happened in
``await_submit``; this node then just releases the run once (the loop may have
moved past the last confirmation, so there is nothing left to wait on).

To force-close a leftover browser, run ``autojob --clean-profile``.
"""

from __future__ import annotations

from src.state import ApplyState

_RELEASE_LOG = {
    "closed": "cleanup: browser left open (run released)",
    "human": "cleanup: browser left open for the human",
    "timeout": "cleanup: browser left open for the human; wait ended",
}


async def cleanup(state: ApplyState) -> ApplyState:
    """Release the browser run; the window is left open for the human."""
    run_id = state.get("browser_run_id")
    if not run_id:
        return {}

    from src.tools.browser import close_run, release_run  # lazy: needs the `browser` extra

    if state.get("task8") is not None:
        # Task 8's loop already waited for the human on each job; release once.
        try:
            await close_run(run_id)
        except Exception as exc:  # noqa: BLE001 - never let cleanup fail the run
            return {"errors": [f"cleanup: {exc}"], "log": ["cleanup: browser release failed"]}
        return {"log": ["cleanup: browser left open (Task 8 loop finished)"]}

    try:
        released = await release_run(run_id, state.get("task4"), progress=print)
    except Exception as exc:  # noqa: BLE001 - never let cleanup fail the run
        return {"errors": [f"cleanup: {exc}"], "log": ["cleanup: browser release failed"]}
    return {"log": [_RELEASE_LOG.get(released, "cleanup: browser left open (run released)")]}


__all__ = ["cleanup"]
