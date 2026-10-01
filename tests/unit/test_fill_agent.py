"""Unit tests for the browser-use fill marshalling (Task 7).

Pure only: no browser, no LLM. These pin the review-facing contract — an answer
with no value, or one the agent reported unfilled, is always flagged rather than
treated as filled.
"""

from __future__ import annotations

from datetime import datetime

from src.nodes import fill
from src.nodes.fill import FillOutcome, artifact_path, normalize_label, reconcile_outcome
from src.tools.store import Answer, Provenance

ANSWERS = (
    Answer("City", "Boston", Provenance.RESUME, 1.0),
    Answer("Do you require sponsorship?", "", Provenance.NEEDS_REVIEW, 0.0),
    Answer("Expected salary", "110000", Provenance.FACTS_RULE, 1.0),
)


def test_normalize_label_drops_required_marker_and_case() -> None:
    assert normalize_label("  Expected  Salary * ") == "expected salary"


def test_artifact_path_is_safe_and_timestamped() -> None:
    path = artifact_path(
        "data/artifacts",
        "4012345678",
        timestamp=datetime(2026, 9, 30, 14, 5, 6),
    )

    assert path.name == "4012345678-20260930T140506.png"
    assert path.parent.name == "artifacts"


def test_artifact_path_sanitises_a_hostile_job_id() -> None:
    path = artifact_path("data/artifacts", "../../etc/passwd")

    assert "/" not in path.name and "\\" not in path.name
    assert path.name.endswith(".png")


def test_empty_answers_are_flagged_not_filled() -> None:
    filled, flagged = reconcile_outcome(FillOutcome(), ANSWERS)

    assert {a.field for a in filled} == {"City", "Expected salary"}
    assert flagged == ("Do you require sponsorship?",)


def test_agent_reported_unfilled_fields_are_flagged() -> None:
    outcome = FillOutcome(filled_fields=["City"], unfilled_fields=["Expected salary"])

    filled, flagged = reconcile_outcome(outcome, ANSWERS)

    assert {a.field for a in filled} == {"City"}
    assert "Expected salary" in flagged
    assert "Do you require sponsorship?" in flagged


def test_reconcile_is_case_and_whitespace_insensitive() -> None:
    outcome = FillOutcome(unfilled_fields=["  expected   salary * "])

    _, flagged = reconcile_outcome(outcome, ANSWERS)

    assert "Expected salary" in flagged


def test_resume_upload_is_reported_through() -> None:
    report_source = FillOutcome(resume_uploaded=True)

    assert report_source.resume_uploaded is True
    assert fill.ARTIFACT_SUFFIX == "png"
