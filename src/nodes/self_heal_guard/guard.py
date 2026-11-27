"""Wrap a graph node so any uncaught exception enters the self-healing loop."""

from __future__ import annotations

import traceback

from src.nodes.self_heal_guard.heal_loop import heal_node_failure
from src.nodes.self_heal_guard.helpers import NodeFn, ReopenMode, _call_node, _reporter
from src.state import ApplyState
from src.tools.crash_logs import note_state


def guard_node(name: str, node_fn: NodeFn, *, reopen: ReopenMode = "job") -> NodeFn:
    """Wrap ``node_fn`` so any uncaught exception enters the self-healing loop."""

    async def guarded(state: ApplyState) -> ApplyState:
        note_state(state, name)  # Task 33: latest state for any crash path
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
                exc=exc,
            )

    guarded.__name__ = getattr(node_fn, "__name__", name)
    guarded.__doc__ = getattr(node_fn, "__doc__", None)
    return guarded


__all__ = ["guard_node"]
