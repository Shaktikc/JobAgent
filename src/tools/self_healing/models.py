"""Data models for the self-healing Easy Apply loop (Task 11).

The models are intentionally browser-free so they can be imported by the graph
state and serialized into a failure bundle. A failure record is written **before**
any recovery is attempted; it carries the fingerprint used to deduplicate repeated
crashes and the path to the evidence captured at the moment of failure.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class JobTarget(BaseModel):
    """The job the run must return to after a browser restart."""

    url: str = ""
    title: str = ""
    company: str = ""
    search_query: str = ""
    login_url: str = ""


class FailureEvidence(BaseModel):
    """Everything observed when the Easy Apply loop hit a hard stop.

    The fields are deliberately plain data (strings/lists/dicts) so the bundle is
    readable by a human and by another agent without importing browser objects.
    """

    stage: str = "fill"
    category: str = "unknown"
    error: str = ""
    traceback: str = ""
    job_title: str = ""
    company: str = ""
    job_url: str = ""
    page_url: str = ""
    page_title: str = ""
    step: str = ""
    step_title: str = ""
    notes: str = ""
    fields: list[dict] = Field(default_factory=list)
    buttons: list[dict] = Field(default_factory=list)
    resume: dict = Field(default_factory=dict)
    visible_text: str = ""
    dom_excerpt: str = ""
    console: list[str] = Field(default_factory=list)
    screenshot_path: str = ""
    captured_at: str = ""
    run_id: str = ""


class HealingAttempt(BaseModel):
    """One recovery action taken after a failure was recorded."""

    attempt: int = 0
    action: str = ""
    success: bool = False
    detail: str = ""


class FailureRecord(BaseModel):
    """A recorded failure, its bug-log identity, and the evidence bundle."""

    fingerprint: str = ""
    category: str = "unknown"
    bug_id: str = ""
    bug_path: str = ""
    bundle_dir: str = ""
    symptom: str = ""
    status: str = "open"
    occurrences: int = 1
    evidence: FailureEvidence = Field(default_factory=FailureEvidence)


class SelfHealingOutcome(BaseModel):
    """What the bounded self-healing loop did during one fill attempt."""

    enabled: bool = True
    attempts: int = 0
    recovered: bool = False
    exhausted: bool = False
    stop_reason: str = ""
    bug_ids: list[str] = Field(default_factory=list)
    failures: list[FailureRecord] = Field(default_factory=list)
    attempt_log: list[HealingAttempt] = Field(default_factory=list)
    last_bundle: str = ""
    notes: str = ""


class CapturedFailure(BaseModel):
    """A failure after evidence capture and fingerprinting."""

    fingerprint: str = ""
    category: str = "unknown"
    symptom: str = ""
    bundle_dir: str = ""
    evidence: FailureEvidence = Field(default_factory=FailureEvidence)


__all__ = [
    "CapturedFailure",
    "FailureEvidence",
    "FailureRecord",
    "HealingAttempt",
    "JobTarget",
    "SelfHealingOutcome",
]
