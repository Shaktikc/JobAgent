"""The graph's shared state for the LinkedIn agent (Tasks 1-8).

Task 1 logs in, searches jobs, and selects the **Easy Apply** filter. Task 2 picks
a job from those results and clicks its **Easy Apply** button, confirming the
application form opens. Task 3 reads the open job's description and chooses the
best-matching resume from the ``resumes/`` folder. Task 4 fills the open Easy
Apply form: the LLM (Task 4.1/10/12) classifies each question and answers it from
the store or, for job-specific free text, the job description + selected resume;
it attaches that resume — without submitting. Task 5 runs
inside that fill: when the LLM cannot answer a question it pauses for the human
(in the browser) and remembers the answer for next time. Task 8 then waits for
the human to submit, opens the next unapplied job, and repeats.

The state is a plain ``TypedDict`` so LangGraph can pass partial updates between
nodes. The ``log``/``errors`` channels use ``operator.add`` so every node can
append to the audit trail without reading the current contents first.
"""

from __future__ import annotations

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
    # Tasks 13/17: the results are limited to the range the user chose at startup
    # (``past_24_hours`` or ``past_week``). ``value`` is that normalized selection
    # so the CLI/verify/log can report it.
    date_posted_filter_selected: bool = False
    date_posted_filter_value: str = ""
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


class JobContextAudit(BaseModel):
    """The small, non-sensitive record of what a fill's job context contained.

    The full job/resume text stays in :class:`JobAnswerContext` (memory and the
    LLM prompt only); this snapshot is what the run state and log may show.
    """

    job_title: str = ""
    company: str = ""
    resume_path: str = ""
    job_chars: int = 0
    resume_chars: int = 0
    profile_available: bool = False
    sources: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class JobAnswerContext(BaseModel):
    """The current job + selected resume, available to answer job questions.

    Task 12 builds a fresh instance for every job (and every self-healed retry).
    ``resume_text`` is excluded from serialisation/repr so the raw resume text is
    never dumped by ``--json`` or written to a log; the prompt uses it directly.
    """

    job_description: JobDescription = Field(default_factory=JobDescription)
    resume_path: str = ""
    resume_text: str = Field(default="", exclude=True, repr=False)
    resume_profile: dict = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)

    @property
    def has_job_description(self) -> bool:
        """True when any part of the current job description was captured."""
        description = self.job_description
        return bool(
            description.title.strip()
            or description.company.strip()
            or description.location.strip()
            or description.body.strip()
        )

    @property
    def has_resume(self) -> bool:
        """True when the selected resume has readable text or a stored profile."""
        return bool(self.resume_text.strip() or self.resume_profile)

    @property
    def sources(self) -> list[str]:
        """The available context sources, in prompt order."""
        available: list[str] = []
        if self.has_resume:
            available.append("resume")
        if self.has_job_description:
            available.append("job_description")
        return available

    def audit(self) -> JobContextAudit:
        """Build the small snapshot recorded on the fill outcome/log."""
        return JobContextAudit(
            job_title=self.job_description.title,
            company=self.job_description.company,
            resume_path=self.resume_path,
            job_chars=len(self.job_description.body),
            resume_chars=len(self.resume_text),
            profile_available=bool(self.resume_profile),
            sources=self.sources,
            errors=list(self.errors),
        )


class Task2Outcome(BaseModel):
    """What the browser observed while selecting a job's Easy Apply button.

    Task 2 reads the job list left open by Task 1, opens the first job that offers
    Easy Apply (skipping external-apply jobs), verifies the button, and reads the
    description. In the match-first flow it stops there (``job_selected``); Task 16
    opens the form only after a resume match. The older one-shot flow may still
    click the button and wait for the form (``easy_apply_clicked`` /
    ``application_form_opened``). The application is never submitted.
    """

    jobs_seen: int = 0
    job_index: int | None = None
    job_title: str = ""
    skipped_jobs: int = 0
    # Task 6: cards that were skipped because they are already "Applied".
    applied_jobs_skipped: int = 0
    applied_skipped_cards: list[dict] = Field(default_factory=list)
    # Task 7: how many results pages were visited while looking for an unapplied
    # job (1 = the first page only; >1 = paginated because whole pages were Applied).
    # Task 17: ``pages_visited`` is the total across the scanned ranges.
    pages_visited: int = 0
    # Task 17: the range the user chose at startup, the range the scan ended on,
    # whether an exhausted primary range was widened to the other range, and how
    # many week pages were scanned.
    date_range_preferred: str = ""
    date_range_used: str = ""
    date_range_fallback_used: bool = False
    pages_visited_past_week: int = 0
    # Task 16: a job and its Easy Apply button were found and its description was
    # read, but the form was deliberately not clicked before the resume match.
    job_selected: bool = False
    easy_apply_button_found: bool = False
    easy_apply_clicked: bool = False
    application_form_opened: bool = False
    modal_text: str = ""
    page_url: str | None = None
    page_title: str | None = None
    screenshot_path: str | None = None
    notes: str = ""
    # Task 3: the description read while the job was open. Captured *before* the
    # Easy Apply form is opened, because on LinkedIn's newer (AI/semantic) job
    # view the inline form can replace the page and hide the description.
    job_description: JobDescription | None = None


class ResumeCandidate(BaseModel):
    """A resume file that was considered for a job (Task 3.2).

    Each resume is summarised by the LLM before matching; ``summary`` is that
    one-line description, and ``described`` records that a description exists (a
    resume without one is an error, never matched from its raw text).
    """

    path: str
    summary: str = ""
    described: bool = False
    rationale: str = ""
    error: str = ""


class Task3Outcome(BaseModel):
    """The resume the agent chose and why (Task 3).

    The **LLM** chooses the best-matching resume from the per-resume descriptions
    (Task 3.2); its decision and rationale are recorded here. When no resume
    matched the job (``no_match``), the agent may ask the human for one in the
    browser (``asked_human`` / ``human_resume_path``), or reuse a resume it
    remembered for a similar job (``reused_from_library``). ``error`` carries a
    Task 3.2 failure (there is no deterministic fallback).
    """

    job_description: JobDescription = Field(default_factory=JobDescription)
    resumes_dir: str = ""
    resumes_found: int = 0
    candidates: list[ResumeCandidate] = Field(default_factory=list)
    selected_path: str | None = None
    rationale: str = ""
    error: str = ""
    # Task 3.1: the "nothing matched, so ask the human" fallback.
    no_match: bool = False
    asked_human: bool = False
    human_resume_path: str = ""
    reused_from_library: str = ""
    # Task 16: the LLM's match quality for the best candidate ("strong",
    # "partial", "none", or "" when the reply did not say). Strict mode applies
    # only to a "strong" match.
    fit: str = ""
    # Task 3.2: the LLM's per-candidate ratings (candidate id -> fit), kept for
    # audit next to the selected path and rationale. Empty when the reply did not
    # include ratings.
    ratings: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


class FormField(BaseModel):
    """One question encountered on the Easy Apply form (Task 4).

    ``answered_by`` records who answered it: ``"llm"`` (Task 4.1 classified the
    question and chose a stored answer), ``"human"`` (Task 5 asked), or
    ``"form"`` (LinkedIn had already filled it). ``question_type`` and
    ``rationale`` carry the LLM's decision so it stays explainable. Task 10 adds
    how the answer was grounded: ``matched_key`` is the stored key a copied answer
    came from, ``derived`` says the answer was reasoned from ``source_keys``
    rather than copied verbatim.
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
    # Task 10: provenance for an answer matched or derived from the store.
    derived: bool = False  # True when the answer was derived, not copied
    source_keys: list[str] = Field(default_factory=list)  # the stored keys used
    # Task 12: provenance for a job-specific answer grounded in the job context.
    answer_source: str = ""  # "resume", "job_description", or "resume+job_description"
    job_specific: bool = False
    context_evidence: list[str] = Field(default_factory=list)
    error: str = ""
