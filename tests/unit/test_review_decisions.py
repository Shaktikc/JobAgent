"""Unit tests for `review-gate` decision logic (Task 8; async in Task 17).

No browser and no real submission: the interactive gate takes an injectable prompt,
output sink and async submit handler, so every approve/reject/edit/quit path is
exercised deterministically.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

import pytest

from src.nodes.review import (
    ReviewAction,
    ReviewResult,
    apply_edit,
    parse_action,
    render_review,
    resolve_outcome,
    review_application,
)
from src.state import JobState
from src.tools.store import Answer, JobStatus, Provenance

JOB: JobState = {
    "job_id": "4012345678",
    "title": "Senior Data Analyst",
    "company": "Acme Analytics",
    "url": "https://www.linkedin.com/jobs/view/4012345678/",
}

ANSWERS = (
    Answer("City", "Boston", Provenance.RESUME, 1.0),
    Answer("Expected salary", "110000", Provenance.FACTS_RULE, 1.0),
    Answer("Do you require sponsorship?", "", Provenance.NEEDS_REVIEW, 0.0),
)


def _run(coro: Coroutine[Any, Any, ReviewResult]) -> ReviewResult:
    return asyncio.run(coro)


class _Prompter:
    """A scripted prompt that records calls and can be exhausted."""

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self._responses:
            raise EOFError
        return self._responses.pop(0)


def _collector() -> tuple[list[str], Callable[[str], None]]:
    lines: list[str] = []
    return lines, lines.append


class _Submit:
    """An async submit handler that records how many times it was awaited."""

    def __init__(self, confirmation: str = "Application sent") -> None:
        self.calls = 0
        self._confirmation = confirmation

    async def __call__(self) -> str:
        self.calls += 1
        return self._confirmation


# --- command parsing --------------------------------------------------------


@pytest.mark.parametrize("raw", ["a", "A", "approve", "y", "yes"])
def test_parse_action_approve(raw: str) -> None:
    assert parse_action(raw) is ReviewAction.APPROVE


@pytest.mark.parametrize("raw", ["r", "R", "reject", "n", "no"])
def test_parse_action_reject(raw: str) -> None:
    assert parse_action(raw) is ReviewAction.REJECT


@pytest.mark.parametrize("raw", ["e", "edit"])
def test_parse_action_edit(raw: str) -> None:
    assert parse_action(raw) is ReviewAction.EDIT


@pytest.mark.parametrize("raw", ["q", "quit", "cancel"])
def test_parse_action_quit(raw: str) -> None:
    assert parse_action(raw) is ReviewAction.QUIT


@pytest.mark.parametrize("raw", ["", "bogus", "  ", "3"])
def test_parse_action_unknown(raw: str) -> None:
    assert parse_action(raw) is None


# --- rendering --------------------------------------------------------------


def test_render_shows_job_resume_and_every_answer_with_provenance() -> None:
    text = render_review(JOB, ANSWERS, resume_file="resumes/data-analyst.pdf")

    assert "Senior Data Analyst" in text
    assert "Acme Analytics" in text
    assert "https://www.linkedin.com/jobs/view/4012345678/" in text
    assert "resumes/data-analyst.pdf" in text
    for answer in ANSWERS:
        assert answer.field in text
        assert answer.provenance.value in text


def test_render_flags_missing_resume() -> None:
    assert "(none)" in render_review(JOB, ANSWERS, resume_file=None)


# --- edits ------------------------------------------------------------------


def test_apply_edit_updates_matching_field_and_preserves_others() -> None:
    edited = apply_edit(ANSWERS, "city", "Cambridge")

    by_field = {a.field: a for a in edited}
    assert by_field["City"].value == "Cambridge"
    assert by_field["City"].provenance is Provenance.RESUME
    assert by_field["Expected salary"].value == "110000"
    assert len(edited) == len(ANSWERS)


def test_apply_edit_does_not_mutate_the_original() -> None:
    apply_edit(ANSWERS, "City", "Cambridge")

    assert {a.field: a.value for a in ANSWERS}["City"] == "Boston"


def test_apply_edit_unknown_field_raises() -> None:
    with pytest.raises(KeyError):
        apply_edit(ANSWERS, "Favorite color", "blue")


# --- outcome mapping --------------------------------------------------------


def test_approve_in_dry_run_never_submits_and_stays_filled() -> None:
    assert resolve_outcome(ReviewAction.APPROVE, dry_run=True) == (False, JobStatus.FILLED)


def test_approve_outside_dry_run_submits_and_marks_applied() -> None:
    assert resolve_outcome(ReviewAction.APPROVE, dry_run=False) == (True, JobStatus.APPLIED)


def test_reject_never_submits_and_marks_rejected() -> None:
    assert resolve_outcome(ReviewAction.REJECT, dry_run=False) == (False, JobStatus.REJECTED)
    assert resolve_outcome(ReviewAction.REJECT, dry_run=True) == (False, JobStatus.REJECTED)


def test_quit_leaves_the_application_filled_and_reofferable() -> None:
    assert resolve_outcome(ReviewAction.QUIT, dry_run=False) == (False, JobStatus.FILLED)


# --- interactive gate -------------------------------------------------------


def test_approve_dry_run_prints_and_does_not_submit() -> None:
    lines, out = _collector()
    submit = _Submit()

    result = _run(
        review_application(
            JOB, ANSWERS, dry_run=True, prompt=_Prompter(["a"]), out=out, submit=submit
        )
    )

    assert isinstance(result, ReviewResult)
    assert result.action is ReviewAction.APPROVE
    assert result.submitted is False
    assert result.status is JobStatus.FILLED
    assert submit.calls == 0
    assert any("Senior Data Analyst" in line for line in lines)


def test_approve_outside_dry_run_submits_exactly_once_and_captures_confirmation() -> None:
    _, out = _collector()
    submit = _Submit("Application sent")

    result = _run(
        review_application(
            JOB,
            ANSWERS,
            dry_run=False,
            prompt=_Prompter(["approve"]),
            out=out,
            submit=submit,
        )
    )

    assert result.submitted is True
    assert result.status is JobStatus.APPLIED
    assert result.confirmation == "Application sent"
    assert submit.calls == 1


def test_reject_marks_rejected_and_submits_nothing() -> None:
    _, out = _collector()
    submit = _Submit()

    result = _run(
        review_application(
            JOB, ANSWERS, dry_run=False, prompt=_Prompter(["r"]), out=out, submit=submit
        )
    )

    assert result.action is ReviewAction.REJECT
    assert result.submitted is False
    assert result.status is JobStatus.REJECTED
    assert submit.calls == 0


def test_edit_updates_the_value_before_submission() -> None:
    _, out = _collector()
    submit = _Submit("done")

    result = _run(
        review_application(
            JOB,
            ANSWERS,
            dry_run=False,
            prompt=_Prompter(["e", "City", "Cambridge", "a"]),
            out=out,
            submit=submit,
        )
    )

    assert {a.field: a.value for a in result.answers}["City"] == "Cambridge"
    assert submit.calls == 1
    assert result.status is JobStatus.APPLIED


def test_invalid_command_reprompts() -> None:
    _, out = _collector()
    prompter = _Prompter(["bogus", "a"])

    result = _run(
        review_application(JOB, ANSWERS, dry_run=True, prompt=prompter, out=out)
    )

    assert result.action is ReviewAction.APPROVE
    assert len(prompter.calls) == 2


def test_interrupt_mid_review_leaves_application_filled() -> None:
    _, out = _collector()
    submit = _Submit()

    def interrupted(_: str) -> str:
        raise KeyboardInterrupt

    result = _run(
        review_application(
            JOB,
            ANSWERS,
            dry_run=False,
            prompt=interrupted,
            out=out,
            submit=submit,
        )
    )

    assert result.action is ReviewAction.QUIT
    assert result.submitted is False
    assert result.status is JobStatus.FILLED
    assert submit.calls == 0


def test_approve_outside_dry_run_without_a_submit_handler_raises() -> None:
    _, out = _collector()

    with pytest.raises(RuntimeError, match="submit"):
        _run(
            review_application(
                JOB, ANSWERS, dry_run=False, prompt=_Prompter(["a"]), out=out, submit=None
            )
        )


def test_needs_review_fields_are_visible_in_the_result() -> None:
    _, out = _collector()

    result = _run(
        review_application(JOB, ANSWERS, dry_run=True, prompt=_Prompter(["a"]), out=out)
    )

    assert any(a.provenance is Provenance.NEEDS_REVIEW for a in result.answers)
