"""Outcome models for the submit-and-repeat loop and the strict resume gate.

Extracted from :mod:`src.state` so that module stays below the project's
file-size limit. ``src.state`` re-exports these names, so existing imports keep
working unchanged:

- :class:`Task8JobRecord` / :class:`Task8Outcome` — what Task 8's loop did.
- :class:`SkippedJobRecord` / :class:`Task16Outcome` — jobs skipped by Task 16
  because no existing resume was a strong match.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Task8JobRecord(BaseModel):
    """One job handled by the Task 8 loop.

    ``outcome`` is how the per-job human-submit wait ended: ``"submitted"`` (the
    human submitted), ``"closed"`` (the human closed the browser), or
    ``"timeout"`` (the wait elapsed). Only a ``"submitted"`` record counts toward
    ``Task8Outcome.jobs_applied``.
    """

    index: int | None = None
    title: str = ""
    company: str = ""
    resume_path: str = ""
    outcome: str = ""


class Task8Outcome(BaseModel):
    """What the Task 8 loop did across a run.

    After the human submits a job, the loop opens the next unapplied job and
    repeats the whole process in the same session. ``jobs`` records each job the
    human submitted (title, company, chosen resume), ``jobs_applied`` counts them,
    and ``stopped_reason`` says why the loop ended (the jobs-per-run cap, no
    unapplied job left, the human closing the browser, a timeout, or a failure).
    """

    iterations: int = 0
    jobs_applied: int = 0
    jobs: list[Task8JobRecord] = Field(default_factory=list)
    max_jobs: int = 0
    stopped_reason: str = ""
    notes: str = ""


class SkippedJobRecord(BaseModel):
    """A job skipped because no existing resume matched it (Task 16)."""

    index: int | None = None
    title: str = ""
    company: str = ""
    fit: str = ""
    rationale: str = ""


class Task16Outcome(BaseModel):
    """What the strict resume gate did across a run (Task 16).

    ``enabled`` mirrors ``AUTOJOB_SESSION_REQUIRE_RESUME_MATCH``. A job is skipped
    when the LLM does not rate an existing resume a strong match; skipped jobs are
    never filled and never count toward ``Task8Outcome.jobs_applied``.
    """

    enabled: bool = True
    jobs_skipped: int = 0
    skipped: list[SkippedJobRecord] = Field(default_factory=list)
    notes: str = ""


__all__ = [
    "SkippedJobRecord",
    "Task8JobRecord",
    "Task8Outcome",
    "Task16Outcome",
]
