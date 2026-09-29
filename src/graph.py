"""The StateGraph builder and compiler.

``langgraph.json`` points at ``build_graph`` in this module. The assembly is
implemented in Task 8 (minimal: single URL -> fill -> review) and completed in
Task 15 (full loop with checkpointing and crash resume).
"""

from __future__ import annotations

from typing import Any


def build_graph() -> Any:
    """Build and compile the AutoJobApply graph.

    Not implemented until Task 8. Raising here keeps the entry point honest:
    nothing silently pretends to work.
    """
    raise NotImplementedError("graph is assembled in Task 8 and completed in Task 15")
