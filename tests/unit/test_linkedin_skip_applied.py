"""Unit tests for Task 6's applied-job skip helpers."""

from __future__ import annotations

from src.configuration import SessionSettings, Settings
from src.state import Task2Outcome
from src.tools.linkedin_skip_applied import (
    applied_skip_note,
    card_is_applied,
    skip_applied_card,
)


def _settings(**session) -> Settings:
    return Settings(session=SessionSettings(**session))


def test_card_is_applied_matches_only_the_applied_status_word() -> None:
    # The Applied status word decides, regardless of the age text that follows.
    assert card_is_applied("Senior Software Engineer Care GP Applied 5 months ago")
    assert card_is_applied("  senior software engineer   applied  · 5 months ago ")
    assert card_is_applied("Backend Engineer Acme Applied")


def test_card_is_applied_ignores_other_statuses_and_age_text() -> None:
    # "Viewed"/"Saved"/"Easy Apply" must not be mistaken for Applied.
    assert not card_is_applied("Senior Software Engineer Care GP Viewed 2 weeks ago Easy Apply")
    assert not card_is_applied("Backend Engineer Acme Saved Easy Apply")
    assert not card_is_applied("Data Engineer Acme Posted 1 week ago Easy Apply")
    assert not card_is_applied("Data Engineer Acme Easy Apply")


def test_card_is_applied_treats_unreadable_card_as_unapplied() -> None:
    assert not card_is_applied("")
    assert not card_is_applied("   ")
    # The word "applied" must be standalone; "applicants"/"applies" is not it.
    assert not card_is_applied("Actively reviewing applicants")
    assert not card_is_applied("Full Stack Engineer Australia (Remote) Easy Apply")


def test_skip_applied_card_records_the_skip_once() -> None:
    outcome = Task2Outcome()
    seen: set[str] = set()
    messages: list[str] = []
    label = "Backend Engineer Acme Applied 5 months ago"
    key = "backend engineer acme applied 5 months ago"

    skipped = skip_applied_card(
        label,
        index=0,
        title=label,
        key=key,
        settings=_settings(),
        outcome=outcome,
        applied_seen=seen,
        notify=messages.append,
    )

    assert skipped is True
    assert outcome.applied_jobs_skipped == 1
    assert outcome.applied_skipped_cards == [{"index": 0, "title": label}]
    assert messages == ["Task 2: job 1 is already applied; skipping."]

    # Re-reading the list must not double-count the same card.
    skip_applied_card(
        label,
        index=0,
        title=label,
        key=key,
        settings=_settings(),
        outcome=outcome,
        applied_seen=seen,
        notify=messages.append,
    )
    assert outcome.applied_jobs_skipped == 1
    assert len(messages) == 1


def test_skip_applied_card_leaves_unapplied_cards_alone() -> None:
    outcome = Task2Outcome()

    skipped = skip_applied_card(
        "Data Engineer Acme Easy Apply",
        index=0,
        title="Data Engineer Acme Easy Apply",
        key="data engineer acme easy apply",
        settings=_settings(),
        outcome=outcome,
        applied_seen=set(),
        notify=lambda _m: None,
    )

    assert skipped is False
    assert outcome.applied_jobs_skipped == 0
    assert outcome.applied_skipped_cards == []


def test_skip_applied_card_can_be_disabled() -> None:
    outcome = Task2Outcome()

    skipped = skip_applied_card(
        "Backend Engineer Acme Applied 5 months ago",
        index=0,
        title="Backend Engineer Acme Applied 5 months ago",
        key="backend engineer acme applied 5 months ago",
        settings=_settings(skip_applied=False),
        outcome=outcome,
        applied_seen=set(),
        notify=lambda _m: None,
    )

    assert skipped is False
    assert outcome.applied_jobs_skipped == 0


def test_applied_skip_note_reports_every_card_applied() -> None:
    note = applied_skip_note(Task2Outcome(jobs_seen=2, applied_jobs_skipped=2))

    assert note is not None
    assert "no unapplied job found" in note


def test_applied_skip_note_reports_partial_skips() -> None:
    note = applied_skip_note(Task2Outcome(jobs_seen=5, applied_jobs_skipped=2))

    assert note is not None
    assert "skipped 2 applied job(s)" in note


def test_applied_skip_note_is_none_without_skips() -> None:
    assert applied_skip_note(Task2Outcome(jobs_seen=3)) is None
