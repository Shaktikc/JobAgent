"""Close the live browser session before the run is verified.

Tasks 2-4 share one session kept open by the ``browse`` node. Whatever path the
run takes (success, a matching failure, or a skipped fill), this node closes it,
so no Chromium window is left behind.
"""

from __future__ import annotations

from src.state import ApplyState


async def cleanup(state: ApplyState) -> ApplyState:
    """Kill the registered browser session, if one is still open."""
    run_id = state.get("browser_run_id")
    if not run_id:
        return {}

    from src.tools.browser import close_run  # lazy: needs the `browser` extra

    try:
        await close_run(run_id)
    except Exception as exc:  # noqa: BLE001 - never let cleanup fail the run
        return {"errors": [f"cleanup: {exc}"], "log": ["cleanup: browser close failed"]}
    return {"log": ["cleanup: browser session closed"]}


__all__ = ["cleanup"]
