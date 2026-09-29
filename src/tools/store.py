"""`state` — SQLite persistence, dedupe, and crash-resume queries.

Implemented in Task 2. NOTE: this is persistence. LangGraph graph channels live in
``src/state.py`` — the two must never share a name (SPEC.md §4).

Tables: jobs (deduped by LinkedIn job id, status enumerated), answers (field, value,
provenance, confidence), and the resume index (file hash -> role keywords).
"""

from __future__ import annotations

# TODO(Task 2)
