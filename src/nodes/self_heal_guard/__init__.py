"""Always-on crash guard for the graph nodes (Task 11).

The fill node owns its own recovery path. Every other node used to catch a
browser/runtime exception and turn it into a plain ``status="failed"`` update, so
a crash in ``next_job``, ``await_submit``, ``browse`` or ``match`` ended the run
without ever recording evidence, closing the stale browser, repairing, or
resuming the same step.

:func:`guard_node` wraps a node and applies the bounded self-healing loop to any
**uncaught** exception:

1. Capture evidence and record the failure (BUG-NNN) while the failed page is
   still open.
2. Close the run cleanly (force-close, verify the profile lock cleared).
3. Run the optional repair command and tests.
4. Reopen the browser (the same job form, or the same results page) and retry
   the **same node** with the recovered run id.
5. Stop after the configured attempt cap, preserving the evidence and marking
   the bug open.

Nothing here clicks **Submit application**.
"""

from src.nodes.self_heal_guard.guard import guard_node
from src.nodes.self_heal_guard.heal_loop import heal_node_failure
from src.nodes.self_heal_guard.helpers import (
    NodeFn,
    ReopenMode,
    _call_node,
    _failed_result,
    _merge_recovered,
    _reopen_results,
    _reporter,
    _target_with_live_url,
)

__all__ = [
    "NodeFn",
    "ReopenMode",
    "_call_node",
    "_failed_result",
    "_merge_recovered",
    "_reopen_results",
    "_reporter",
    "_target_with_live_url",
    "guard_node",
    "heal_node_failure",
]
