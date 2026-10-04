"""The graph's shared state for the LinkedIn agent (Task 1 + Task 2).

Task 1 logs in, searches jobs, and selects the **Easy Apply** filter. Task 2 then
picks a job from those results and clicks its **Easy Apply** button, confirming
the application form opens (nothing is submitted).

The state is a plain ``TypedDict`` so LangGraph can pass partial updates between
nodes. The ``log``/``errors`` channels use ``operator.add`` so every node can
append to the audit trail without reading the current contents first.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field

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


class Task2Outcome(BaseModel):
    """What the browser observed while selecting a job's Easy Apply button.

    Task 2 reads the job list left open by Task 1, opens the first job that has
    an Easy Apply button (skipping external-apply jobs), clicks it, and waits for
    the Easy Apply application form to appear. The application is never
    submitted.
    """

    jobs_seen: int = 0
    job_index: int | None = None
    job_title: str = ""
    skipped_jobs: int = 0
    easy_apply_button_found: bool = False
    easy_apply_clicked: bool = False
    application_form_opened: bool = False
    modal_text: str = ""
    page_url: str | None = None
    page_title: str | None = None
    screenshot_path: str | None = None
    notes: str = ""


class AgentOutcome(BaseModel):
    """Both task outcomes produced by a single browser run."""

    task1: Task1Outcome = Field(default_factory=Task1Outcome)
    task2: Task2Outcome = Field(default_factory=Task2Outcome)


class ApplyState(TypedDict, total=False):
    """State threaded through the agent graph."""

    # --- input ---
    url: str
    search_query: str
    dry_run: bool

    # --- results ---
    task1: Task1Outcome
    task2: Task2Outcome

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
    """Build a well-formed initial state for a single agent run."""
    return ApplyState(
        url=url,
        search_query=search_query,
        dry_run=dry_run,
        status="pending",
        log=[],
        errors=[],
    )
