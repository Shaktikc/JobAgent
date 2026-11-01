"""Task 9: the on-page status panel and the BUG-067 input lock.

Split by concern so each module stays small:

* :mod:`.panel_js` — the panel's DOM scripts and LLM line formatting.
* :mod:`.status_reporter` — the CLI + panel reporter and its emit helpers.
* :mod:`.interaction_lock` — the per-page lock that blocks physical input while
  the agent works and unlocks it for a human turn.

This module re-exports the public API, so existing imports such as
``from src.tools.linkedin_status_overlay import emit_step`` keep working
unchanged.
"""

from __future__ import annotations

from src.tools.linkedin_status_overlay.interaction_lock import (
    InteractionLock,
    begin_human_turn,
    end_human_turn,
    ensure_interaction_lock,
    release_all_interaction_locks,
    release_interaction_lock,
)
from src.tools.linkedin_status_overlay.panel_js import (
    _CLEAR_STATUS_JS,
    _LLM_PREFIX,
    _UPDATE_STATUS_JS,
    _format_llm,
)
from src.tools.linkedin_status_overlay.status_reporter import (
    StatusReporter,
    emit_llm,
    emit_step,
)

__all__ = [
    "InteractionLock",
    "StatusReporter",
    "_CLEAR_STATUS_JS",
    "_LLM_PREFIX",
    "_UPDATE_STATUS_JS",
    "_format_llm",
    "begin_human_turn",
    "emit_llm",
    "emit_step",
    "end_human_turn",
    "ensure_interaction_lock",
    "release_all_interaction_locks",
    "release_interaction_lock",
]
