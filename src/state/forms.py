"""Application form and human-answer outcome models."""

from pydantic import BaseModel, Field

from src.state.outcomes import FormField, JobContextAudit
from src.state.validation import ValidationFailure


class Task4Outcome(BaseModel):
    """What happened while filling the Easy Apply form (Task 4).

    Each question is classified by the LLM (Task 4.1/10), which answers it from the
    store (copying a stored answer or deriving one the stored entries entail);
    questions it cannot ground are left for Task 5 and recorded in
    ``unknown_fields``. The chosen resume is preferred from the form's own resume
    list; it is only uploaded when nothing listed matches. The application is
    not submitted by the fill walk. Task 22 can then submit in automatic mode.
    """

    form_open: bool = False
    steps_advanced: int = 0
    # Task 4: the walk stopped at the terminal step (only **Submit application**
    # remains). Task 22's startup choice controls who submits next.
    reached_terminal_step: bool = False
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
    # Task 22: set before clicking; an uncertain result must never trigger a second click.
    submission_attempted: bool = False
    screenshot_path: str | None = None
    page_url: str | None = None
    # Task 12: what the per-job context contained (sources/counts, never raw text).
    job_context: JobContextAudit = Field(default_factory=JobContextAudit)
    notes: str = ""
    validation: ValidationFailure = Field(default_factory=ValidationFailure)

    @property
    def awaiting_human_submit(self) -> bool:
        """True when the walk stopped at the last step and nothing was submitted.

        The fill walk leaves the form ready. Manual runs leave the browser open
        for the human to review, submit, and close it themselves.
        """
        return self.reached_terminal_step and not self.submitted and not self.validation.issues


class Task5Outcome(BaseModel):
    """What happened while asking the human about unknown questions (Task 5).

    Task 5 runs inside the Task 4 fill: a question the LLM (Task 4.1/10) cannot
    answer pauses the run, shows a browser banner explaining the agent does not
    know the answer, and waits for the human to type the answer into the form
    field. The answer is remembered in the answer store so Task 4.1/10 can reuse it
    next time.
    """

    enabled: bool = False
    asked: int = 0
    answered: int = 0
    skipped: int = 0
    timed_out: int = 0
    answered_questions: list[str] = Field(default_factory=list)
    notes: str = ""
