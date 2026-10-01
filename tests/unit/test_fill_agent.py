"""Unit tests for the browser-use fill marshalling (Task 7).

Pure only: no browser, no LLM. These pin the review-facing contract — an answer
with no value, or one the agent reported unfilled, is always flagged rather than
treated as filled.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

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


def test_unrecognized_fields_the_agent_reported_are_surfaced() -> None:
    """Fields we never asked about must still reach the review, never vanish.

    Live CP-B (job 4473985692) reported four extra required questions in
    ``unfilled_fields``; they were dropped because only labels we supplied were
    reconciled. They must be flagged so the human sees them.
    """
    outcome = FillOutcome(
        unfilled_fields=[
            "Are you willing to undergo a background check?",
            "Are you comfortable working in an onsite setting?",
        ]
    )

    filled, flagged = reconcile_outcome(outcome, ANSWERS)

    assert {a.field for a in filled} == {"City", "Expected salary"}
    assert "Are you willing to undergo a background check?" in flagged
    assert "Are you comfortable working in an onsite setting?" in flagged


def test_resume_upload_is_reported_through() -> None:
    report_source = FillOutcome(resume_uploaded=True)

    assert report_source.resume_uploaded is True
    assert fill.ARTIFACT_SUFFIX == "png"


# --- a hard failure still leaves a screenshot, then propagates (criterion 12) ---


class _FailingAgent:
    """A ``browser_agent.run_task`` stub that always raises."""

    async def __call__(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError("agent exploded")


class _Browser:
    def __init__(self) -> None:
        self.screenshots: list[str] = []

    async def take_screenshot(self, *, path: str) -> None:
        self.screenshots.append(path)


def test_fill_captures_a_failure_screenshot_then_reraises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(fill.browser_agent, "run_task", _FailingAgent())
    browser = _Browser()

    with pytest.raises(RuntimeError, match="agent exploded"):
        asyncio.run(
            fill.fill_application(
                browser,
                object(),
                None,
                {"job_id": "job-7", "title": "Role", "company": "Co", "url": "https://x/"},
                (),
                resume_path=None,
                artifacts_dir=tmp_path,
            )
        )

    assert len(browser.screenshots) == 1
    assert browser.screenshots[0].endswith("failure.png")
    assert "job-7" in browser.screenshots[0]


def test_failure_screenshot_error_does_not_mask_the_original(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _DeadBrowser:
        async def take_screenshot(self, *, path: str) -> None:
            raise RuntimeError("browser gone")

    monkeypatch.setattr(fill.browser_agent, "run_task", _FailingAgent())

    with pytest.raises(RuntimeError, match="agent exploded"):
        asyncio.run(
            fill.fill_application(
                _DeadBrowser(),
                object(),
                None,
                {"job_id": "job-8"},
                (),
                resume_path=None,
                artifacts_dir=tmp_path,
            )
        )
