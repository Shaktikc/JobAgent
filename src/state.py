"""The graph's shared state for the LinkedIn agent (Tasks 1-5).

Task 1 logs in, searches jobs, and selects the **Easy Apply** filter. Task 2 picks
a job from those results and clicks its **Easy Apply** button, confirming the
application form opens. Task 3 reads the open job's description and chooses the
best-matching resume from the ``resumes/`` folder. Task 4 fills the open Easy
Apply form: the LLM (Task 4.1) classifies each question and chooses the answer
from the store, and attaches that resume — without submitting. Task 5 runs
inside that fill: when the LLM cannot answer a question it pauses for the human
(in the browser) and remembers the answer for next time.

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
    ai_job_search_present: bool = False
    ai_job_search_clicked: bool = False
    ai_job_search_clicks: int = 0
    ai_job_search_candidates: list[str] = Field(default_factory=list)
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
    # Task 6: cards that were skipped because they are already "Applied".
    applied_jobs_skipped: int = 0
    applied_skipped_cards: list[dict] = Field(default_factory=list)
    easy_apply_button_found: bool = False
    easy_apply_clicked: bool = False
    application_form_opened: bool = False
    modal_text: str = ""
    page_url: str | None = None
    page_title: str | None = None
    screenshot_path: str | None = None
    notes: str = ""


class JobDescription(BaseModel):
    """The job details read from the open job's details pane (Task 3)."""

    title: str = ""
    company: str = ""
    location: str = ""
    body: str = ""
    page_url: str | None = None

    @property
    def is_read(self) -> bool:
        """True when at least a title or a description body was captured."""
        return bool(self.title.strip() or self.body.strip())

    @property
    def full_text(self) -> str:
        """Title + company + location + body joined into one searchable blob."""
        parts = (self.title, self.company, self.location, self.body)
        return " ".join(part for part in parts if part)


class ResumeCandidate(BaseModel):
    """A resume file that was considered, with its fit score."""

    path: str
    score: float = 0.0
    matched_keywords: list[str] = Field(default_factory=list)
    rationale: str = ""
    extracted: bool = False
    error: str = ""


class Task3Outcome(BaseModel):
    """The resume the agent chose and why (Task 3)."""

    job_description: JobDescription = Field(default_factory=JobDescription)
    resumes_dir: str = ""
    resumes_found: int = 0
    candidates: list[ResumeCandidate] = Field(default_factory=list)
    selected_path: str | None = None
    selected_score: float | None = None
    rationale: str = ""
    tie_break: str = ""
    notes: str = ""


class FormField(BaseModel):
    """One question encountered on the Easy Apply form (Task 4).

    ``answered_by`` records who answered it: ``"llm"`` (Task 4.1 classified the
    question and chose a stored answer), ``"human"`` (Task 5 asked), or
    ``"form"`` (LinkedIn had already filled it). ``question_type`` and
    ``rationale`` carry the LLM's decision so it stays explainable.
    """

    question: str = ""
    option: str = ""
    field_type: str = ""
    name: str = ""
    known: bool = False
    filled: bool = False
    value: str = ""
    options: list[str] = Field(default_factory=list)
    required: bool = False
    answered_by: str = ""  # "llm" (Task 4.1), "human" (Task 5), or "form"
    question_type: str = ""  # the LLM's classification of the question
    matched_key: str = ""  # the stored question the LLM chose the answer from
    rationale: str = ""  # why the LLM chose this answer
    error: str = ""


class Task4Outcome(BaseModel):
    """What happened while filling the Easy Apply form (Task 4).

    Each question is classified by the LLM (Task 4.1), which chooses a stored
    answer; questions it cannot answer are left for Task 5 and recorded in
    ``unknown_fields``. The chosen resume is preferred from the form's own resume
    list; it is only uploaded when nothing listed matches. The application is
    never submitted.
    """

    form_open: bool = False
    steps_advanced: int = 0
    fields: list[FormField] = Field(default_factory=list)
    fields_enumerated: int = 0
    known_fields: int = 0
    filled_fields: int = 0
    unknown_fields: list[str] = Field(default_factory=list)
    resume_attached: bool = False
    resume_selection: str = ""  # "listed" or "uploaded"
    resume_listed_name: str = ""
    resume_path: str = ""
    upload_attempted: bool = False
    submitted: bool = False
    screenshot_path: str | None = None
    page_url: str | None = None
    notes: str = ""


class Task5Outcome(BaseModel):
    """What happened while asking the human about unknown questions (Task 5).

    Task 5 runs inside the Task 4 fill: a question the LLM (Task 4.1) cannot
    answer pauses the run, shows a browser banner explaining the agent does not
    know the answer, and waits for the human to type the answer into the form
    field. The answer is remembered in the answer store so Task 4.1 can reuse it
    next time.
    """

    enabled: bool = False
    asked: int = 0
    answered: int = 0
    skipped: int = 0
    timed_out: int = 0
    answered_questions: list[str] = Field(default_factory=list)
    notes: str = ""


class AgentOutcome(BaseModel):
    """What a single browser run produced (Tasks 1-5)."""

    task1: Task1Outcome = Field(default_factory=Task1Outcome)
    task2: Task2Outcome = Field(default_factory=Task2Outcome)
    job_description: JobDescription = Field(default_factory=JobDescription)
    task3: Task3Outcome = Field(default_factory=Task3Outcome)
    task4: Task4Outcome = Field(default_factory=Task4Outcome)
    task5: Task5Outcome = Field(default_factory=Task5Outcome)


class ApplyState(TypedDict, total=False):
    """State threaded through the agent graph."""

    # --- input ---
    url: str
    search_query: str
    dry_run: bool
    resumes_dir: str

    # --- results ---
    task1: Task1Outcome
    task2: Task2Outcome
    job_description: JobDescription
    task3: Task3Outcome
    task4: Task4Outcome
    task5: Task5Outcome

    # --- live browser session handle (Tasks 2-4 share one session) ---
    browser_run_id: str

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
    resumes_dir: str = "",
) -> ApplyState:
    """Build a well-formed initial state for a single agent run."""
    return ApplyState(
        url=url,
        search_query=search_query,
        dry_run=dry_run,
        resumes_dir=resumes_dir,
        status="pending",
        log=[],
        errors=[],
    )
