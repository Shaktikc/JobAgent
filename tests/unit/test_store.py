"""Unit tests for `state` — SQLite persistence, dedupe, and crash-resume queries (Task 2).

In-memory SQLite only: no network, no browser, no filesystem. Every test sets up and
tears down its own database.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from src.tools.store import (
    Answer,
    Job,
    JobStatus,
    Provenance,
    ResumeIndexEntry,
    connect,
    count_applied_today,
    get_answers,
    get_job,
    get_resume_index,
    init_db,
    record_answer,
    set_job_status,
    transaction,
    upsert_job,
    upsert_resume_index,
)


def _db() -> sqlite3.Connection:
    conn = connect(":memory:")
    init_db(conn)
    return conn


def test_init_db_is_idempotent_and_creates_expected_tables() -> None:
    conn = connect(":memory:")

    init_db(conn)
    init_db(conn)

    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }

    assert {"jobs", "answers", "resume_index"} <= names


def test_status_values_are_exactly_the_six() -> None:
    assert {status.value for status in JobStatus} == {
        "seen",
        "skipped",
        "filled",
        "rejected",
        "applied",
        "failed",
    }


def test_provenance_values_match_the_spec() -> None:
    assert {p.value for p in Provenance} == {
        "RESUME",
        "FACTS_RULE",
        "LLM_GUESS",
        "NEEDS_REVIEW",
    }


def test_jobs_dedupe_by_job_id() -> None:
    conn = _db()

    upsert_job(conn, Job(job_id="42", title="Data Analyst", company="Acme"))
    upsert_job(conn, Job(job_id="42", title="Data Analyst II", company="Acme"))

    count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert count == 1
    assert get_job(conn, "42").title == "Data Analyst II"


def test_upsert_preserves_created_at_and_refreshes_updated_at() -> None:
    conn = _db()

    upsert_job(conn, Job(job_id="1", title="First"))
    created_at = get_job(conn, "1").created_at

    upsert_job(conn, Job(job_id="1", title="Second"))
    reloaded = get_job(conn, "1")

    assert reloaded is not None
    assert reloaded.created_at == created_at
    assert reloaded.updated_at is not None


def test_get_job_returns_none_when_missing() -> None:
    assert get_job(_db(), "nope") is None


def test_set_job_status_rejects_unknown_values() -> None:
    conn = _db()
    upsert_job(conn, Job(job_id="1"))

    with pytest.raises(ValueError):
        set_job_status(conn, "1", "not-a-status")


def test_set_job_status_marks_applied_with_timestamp() -> None:
    conn = _db()
    upsert_job(conn, Job(job_id="1"))

    set_job_status(conn, "1", JobStatus.APPLIED)

    applied = get_job(conn, "1")
    assert applied is not None
    assert applied.status is JobStatus.APPLIED
    assert applied.applied_at is not None


def test_answer_records_field_value_provenance_and_confidence() -> None:
    conn = _db()
    upsert_job(conn, Job(job_id="1"))

    record_answer(conn, "1", Answer("salary", "110000", Provenance.FACTS_RULE, 1.0))

    answers = get_answers(conn, "1")
    assert len(answers) == 1
    assert answers[0] == Answer("salary", "110000", Provenance.FACTS_RULE, 1.0)


def test_recording_same_field_twice_updates_in_place() -> None:
    conn = _db()
    upsert_job(conn, Job(job_id="1"))

    record_answer(conn, "1", Answer("salary", "100000", Provenance.LLM_GUESS, 0.4))
    record_answer(conn, "1", Answer("salary", "110000", Provenance.FACTS_RULE, 1.0))

    answers = get_answers(conn, "1")
    assert len(answers) == 1
    assert answers[0].value == "110000"
    assert answers[0].provenance is Provenance.FACTS_RULE


def test_answer_requires_an_existing_job() -> None:
    conn = _db()

    with pytest.raises(sqlite3.IntegrityError):
        record_answer(conn, "missing", Answer("x", "y", Provenance.NEEDS_REVIEW, 0.0))


def test_count_applied_today_counts_only_todays_applied_jobs() -> None:
    conn = _db()
    # Use the store's own clock: `set_job_status` stamps `applied_at` from local now,
    # and `_now_iso` documents that its date prefix is the local calendar day.
    today = date.today()
    yesterday = today - timedelta(days=1)

    upsert_job(conn, Job(job_id="a"))
    set_job_status(conn, "a", JobStatus.APPLIED)

    upsert_job(conn, Job(job_id="b"))
    set_job_status(conn, "b", JobStatus.APPLIED)

    conn.execute(
        "UPDATE jobs SET applied_at = ? WHERE job_id = 'b'",
        (f"{yesterday.isoformat()}T10:00:00+00:00",),
    )

    upsert_job(conn, Job(job_id="c"))
    set_job_status(conn, "c", JobStatus.REJECTED)

    assert count_applied_today(conn, today=today) == 1


def test_count_applied_today_is_zero_on_empty_db() -> None:
    assert count_applied_today(_db()) == 0


def test_failed_transaction_leaves_no_partial_row() -> None:
    conn = _db()

    with pytest.raises(RuntimeError), transaction(conn):
        upsert_job(conn, Job(job_id="1", title="Half-written"))
        raise RuntimeError("simulated crash mid-write")

    assert get_job(conn, "1") is None


def test_resume_index_round_trips_by_file_hash() -> None:
    conn = _db()
    entry = ResumeIndexEntry(
        file_hash="abc123",
        file_path="resumes/whatever.pdf",
        role_keywords=("data analyst", "bi analyst"),
    )

    upsert_resume_index(conn, entry)

    assert get_resume_index(conn, "abc123") == entry
    assert get_resume_index(conn, "nope") is None


def test_resume_index_reindex_replaces_keywords_for_same_hash() -> None:
    conn = _db()
    upsert_resume_index(conn, ResumeIndexEntry("h1", "a.pdf", ("old",)))
    upsert_resume_index(conn, ResumeIndexEntry("h1", "a.pdf", ("new", "terms")))

    entry = get_resume_index(conn, "h1")
    assert entry is not None
    assert entry.role_keywords == ("new", "terms")
