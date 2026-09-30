"""LangGraph state definitions: shared memory and graph channels.

NOTE: this is the *graph* state. Persistence is a separate concern and lives in
``src/tools/store.py`` — the two must never share a name (SPEC.md §4).

``JobState`` is introduced in Task 5 (``discovery`` emits it) and extended in
Task 8 (answers / review) and Task 15 (the run loop). It stays intentionally
small until a task needs more.
"""

from __future__ import annotations

from typing import TypedDict


class JobState(TypedDict, total=False):
    """One discovered job, passed from ``discovery`` to later graph nodes.

    ``job_id`` is the LinkedIn job id (the dedupe key used by ``tools/store.py``).
    """

    job_id: str
    title: str
    company: str
    url: str
    description: str
    easy_apply: bool
