"""The graph's shared state for Task 1: log in, search jobs, select Easy Apply.

The state is a plain ``TypedDict`` so LangGraph can pass partial updates between
nodes. The ``log``/``errors`` channels use ``operator.add`` so every node can
append to the audit trail without reading the current contents first.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from pydantic import BaseModel

DEFAULT_LOGIN_URL = "https://www.linkedin.com/login/"
DEFAULT_SEARCH_QUERY = "software engineer"


class Task1Outcome(BaseModel):
    """What the browser observed while logging in and searching."""

    start_url: str | None = None
    page_url: str | None = None
    page_title: str | None = None
    already_logged_in: bool = False
    logged_in: bool = False
    search_query: str = ""
    search_url: str | None = None
    search_performed: bool = False
    results_found: bool = False
    results_count: int = 0
    easy_apply_filter_selected: bool = False
    screenshot_path: str | None = None
    notes: str = ""


class ApplyState(TypedDict, total=False):
    """State threaded through the Task 1 graph."""

    # --- input ---
    url: str
    search_query: str
    dry_run: bool

    # --- results ---
    outcome: Task1Outcome

    # --- control flow ---
    status: str

    # --- audit trail (append-only) ---
    log: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]


def new_state(
    url: str = DEFAULT_LOGIN_URL,
    *,
    search_query: str = DEFAULT_SEARCH_QUERY,
    dry_run: bool = True,
) -> ApplyState:
    """Build a well-formed initial state for a single Task 1 run."""
    return ApplyState(
        url=url,
        search_query=search_query,
        dry_run=dry_run,
        status="pending",
        log=[],
        errors=[],
    )
