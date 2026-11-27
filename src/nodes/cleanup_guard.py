"""Task 33: record a ``cleanup`` crash without changing what cleanup does.

``cleanup`` stays outside self-healing so a release failure can never relaunch
the browser. This guard only writes a crash bundle (with best-effort page
evidence) and re-raises the same exception, so the run ends exactly as before.
"""

from __future__ import annotations

from src.nodes.self_heal_guard import NodeFn, _call_node
from src.state import ApplyState
from src.tools.crash_logs import note_state, record_crash_async


def guard_cleanup(node_fn: NodeFn) -> NodeFn:
    async def guarded(state: ApplyState) -> ApplyState:
        note_state(state, "cleanup")
        try:
            return await _call_node(node_fn, state)
        except Exception as exc:
            await record_crash_async(
                "cleanup_crash", exc=exc, stage="cleanup", state=dict(state), exit_code=1
            )
            raise

    guarded.__name__ = getattr(node_fn, "__name__", "cleanup")
    guarded.__doc__ = getattr(node_fn, "__doc__", None)
    return guarded


__all__ = ["guard_cleanup"]
