"""Keep manual waiting recoverable; never replay automatic submission on a crash."""

from src.nodes.self_heal_guard import NodeFn, _call_node, guard_node
from src.state import ApplyState, Task8Outcome


def guard_submission(node_fn: NodeFn) -> NodeFn:
    manual_wait = guard_node("await_submit", node_fn, reopen="job")

    async def guarded(state: ApplyState) -> ApplyState:
        if state.get("submission_mode") != "auto":
            return await manual_wait(state)
        try:
            return await _call_node(node_fn, state)
        except Exception:
            # A request can reach LinkedIn even if the browser connection fails.
            # Preserve this page and mode; reopening/retrying could submit twice.
            task8 = state.get("task8") or Task8Outcome()
            task8.last_submission_status = "interrupted"
            task8.stopped_reason = (
                "automatic submission interrupted; review this application manually"
            )
            return {"task8": task8, "status": "needs_review",
                    "log": [f"await_submit: {task8.stopped_reason}"]}

    return guarded
