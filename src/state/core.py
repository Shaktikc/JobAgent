"""Graph state, defaults, and aggregate run outcomes."""

import operator
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field

from src.date_range import DEFAULT_DATE_RANGE, normalize_date_range
from src.state.forms import Task4Outcome, Task5Outcome
from src.state.outcomes import (
    DEFAULT_LOGIN_URL,
    DEFAULT_SEARCH_QUERY,
    JobAnswerContext,
    JobDescription,
    Task1Outcome,
    Task2Outcome,
    Task3Outcome,
)
from src.state.validation import Task20Outcome
from src.state_loop import Task8Outcome, Task16Outcome
from src.tools.self_healing.models import SelfHealingOutcome


class AgentOutcome(BaseModel):
    """What a single browser run produced (Tasks 1-5)."""

    task1: Task1Outcome = Field(default_factory=Task1Outcome)
    task2: Task2Outcome = Field(default_factory=Task2Outcome)
    job_description: JobDescription = Field(default_factory=JobDescription)
    task3: Task3Outcome = Field(default_factory=Task3Outcome)
    task4: Task4Outcome = Field(default_factory=Task4Outcome)
    task5: Task5Outcome = Field(default_factory=Task5Outcome)
    task8: Task8Outcome = Field(default_factory=Task8Outcome)
    task16: Task16Outcome = Field(default_factory=Task16Outcome)
    task20: Task20Outcome = Field(default_factory=Task20Outcome)


class ApplyState(TypedDict, total=False):
    """State threaded through the agent graph."""

    # --- input ---
    url: str
    search_query: str
    dry_run: bool
    resumes_dir: str
    # Task 17: the range the user chose at startup (``past_24_hours`` or
    # ``past_week``). The scan starts here and falls back to the other range.
    date_range: str
    # Task 22: opt in once per run; omitted/unknown modes never auto-submit.
    submission_mode: str

    # --- results ---
    task1: Task1Outcome
    task2: Task2Outcome
    job_description: JobDescription
    task3: Task3Outcome
    task4: Task4Outcome
    task5: Task5Outcome
    task8: Task8Outcome
    task16: Task16Outcome
    task20: Task20Outcome
    self_healing: SelfHealingOutcome
    # Task 12: the current job + selected resume (rebuilt for every job).
    job_context: JobAnswerContext

    # --- live browser session handle (Tasks 2-4 share one session) ---
    browser_run_id: str

    # --- control flow ---
    status: str

    # --- audit trail (append-only) ---
    log: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    # Task 16: normalized titles skipped for having no matching resume. Kept
    # append-only so later passes of the loop never re-open the same job.
    skipped_titles: Annotated[list[str], operator.add]
    skipped_job_ids: Annotated[list[str], operator.add]


def new_state(
    url: str = DEFAULT_LOGIN_URL,
    *,
    search_query: str = DEFAULT_SEARCH_QUERY,
    dry_run: bool = True,
    resumes_dir: str = "",
    date_range: str = DEFAULT_DATE_RANGE,
    submission_mode: str = "manual",
) -> ApplyState:
    """Build a well-formed initial state for a single agent run."""
    return ApplyState(
        url=url,
        search_query=search_query,
        dry_run=dry_run,
        resumes_dir=resumes_dir,
        date_range=normalize_date_range(date_range) or DEFAULT_DATE_RANGE,
        submission_mode=submission_mode,
        status="pending",
        log=[],
        errors=[],
        skipped_titles=[],
        skipped_job_ids=[],
    )
