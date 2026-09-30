"""`state` — SQLite persistence, dedupe, and crash-resume queries.

Implemented in Task 2. NOTE: this is persistence. LangGraph graph channels live in
``src/state.py`` — the two must never share a name (SPEC.md §4).

Tables: jobs (deduped by LinkedIn job id, status enumerated), answers (field, value,
provenance, confidence), and the resume index (file hash -> role keywords).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path


class JobStatus(StrEnum):
    """The only legal job states (SPEC.md §9)."""

    SEEN = "seen"
    SKIPPED = "skipped"
    FILLED = "filled"
    REJECTED = "rejected"
    APPLIED = "applied"
    FAILED = "failed"


class Provenance(StrEnum):
    """Where an answer came from. Every stored answer carries one (SPEC.md §5)."""

    RESUME = "RESUME"
    FACTS_RULE = "FACTS_RULE"
    LLM_GUESS = "LLM_GUESS"
    NEEDS_REVIEW = "NEEDS_REVIEW"


_STATUS_VALUES = tuple(status.value for status in JobStatus)
_PROVENANCE_VALUES = tuple(p.value for p in Provenance)


@dataclass
class Job:
    """A discovered job. `job_id` is the LinkedIn job id and the dedupe key."""

    job_id: str
    title: str = ""
    company: str = ""
    url: str = ""
    description: str = ""
    status: JobStatus = JobStatus.SEEN
    resume_file: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    applied_at: str | None = None


@dataclass(frozen=True)
class Answer:
    """One form field's answer, with provenance and confidence."""

    field: str
    value: str
    provenance: Provenance
    confidence: float


@dataclass(frozen=True)
class ResumeIndexEntry:
    """A resume's cached auto-index: file hash -> the roles it targets."""

    file_hash: str
    file_path: str
    role_keywords: tuple[str, ...] = ()


def _sql_list(values: tuple[str, ...]) -> str:
    """Render enum values as a SQL literal list for CHECK constraints."""
    return ", ".join(f"'{value}'" for value in values)


_SCHEMA = (
    f"""
    CREATE TABLE IF NOT EXISTS jobs (
        job_id      TEXT PRIMARY KEY,
        title       TEXT NOT NULL DEFAULT '',
        company     TEXT NOT NULL DEFAULT '',
        url         TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'seen'
            CHECK (status IN ({_sql_list(_STATUS_VALUES)})),
        resume_file TEXT,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        applied_at  TEXT
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS answers (
        job_id     TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
        field      TEXT NOT NULL,
        value      TEXT NOT NULL,
        provenance TEXT NOT NULL
            CHECK (provenance IN ({_sql_list(_PROVENANCE_VALUES)})),
        confidence REAL NOT NULL,
        PRIMARY KEY (job_id, field)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resume_index (
        file_hash     TEXT PRIMARY KEY,
        file_path     TEXT NOT NULL,
        role_keywords TEXT NOT NULL DEFAULT '[]',
        indexed_at    TEXT NOT NULL
    )
    """,
)


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection with row access by name, foreign keys on, autocommit off.

    Writes are single statements (atomic) or wrapped in :func:`transaction`.
    """
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the schema if absent. Safe to call on every run (idempotent)."""
    for statement in _SCHEMA:
        conn.execute(statement)


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run several writes atomically. A crash mid-block leaves no partial row."""
    conn.execute("BEGIN")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def _now_iso() -> str:
    """Local timezone-aware ISO timestamp; its date prefix is the local calendar day."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _coerce_status(value: JobStatus | str) -> JobStatus:
    if isinstance(value, JobStatus):
        return value
    try:
        return JobStatus(value)
    except ValueError as exc:
        raise ValueError(f"invalid job status: {value!r}") from exc


def _coerce_provenance(value: Provenance | str) -> Provenance:
    if isinstance(value, Provenance):
        return value
    try:
        return Provenance(value)
    except ValueError as exc:
        raise ValueError(f"invalid provenance: {value!r}") from exc


def upsert_job(conn: sqlite3.Connection, job: Job) -> None:
    """Insert or update a job keyed by `job_id`. `created_at` is preserved."""
    now = _now_iso()
    status = _coerce_status(job.status)
    applied_at = now if status is JobStatus.APPLIED else None
    conn.execute(
        """
        INSERT INTO jobs
            (job_id, title, company, url, description, status, resume_file,
             created_at, updated_at, applied_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            title       = excluded.title,
            company     = excluded.company,
            url         = excluded.url,
            description = excluded.description,
            status      = excluded.status,
            resume_file = excluded.resume_file,
            updated_at  = excluded.updated_at,
            applied_at  = CASE
                WHEN excluded.status = 'applied' AND jobs.applied_at IS NULL
                THEN excluded.updated_at
                ELSE jobs.applied_at
            END
        """,
        (
            job.job_id,
            job.title,
            job.company,
            job.url,
            job.description,
            status.value,
            job.resume_file,
            now,
            now,
            applied_at,
        ),
    )


def get_job(conn: sqlite3.Connection, job_id: str) -> Job | None:
    row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return Job(
        job_id=row["job_id"],
        title=row["title"],
        company=row["company"],
        url=row["url"],
        description=row["description"],
        status=JobStatus(row["status"]),
        resume_file=row["resume_file"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        applied_at=row["applied_at"],
    )


def set_job_status(
    conn: sqlite3.Connection,
    job_id: str,
    status: JobStatus | str,
    *,
    resume_file: str | None = None,
) -> None:
    """Transition a job's status. Reaching `applied` stamps `applied_at`."""
    resolved = _coerce_status(status)
    now = _now_iso()
    assignments = ["status = ?", "updated_at = ?"]
    params: list[str] = [resolved.value, now]
    if resolved is JobStatus.APPLIED:
        assignments.append("applied_at = ?")
        params.append(now)
    if resume_file is not None:
        assignments.append("resume_file = ?")
        params.append(resume_file)
    params.append(job_id)
    cursor = conn.execute(
        f"UPDATE jobs SET {', '.join(assignments)} WHERE job_id = ?", params
    )
    if cursor.rowcount == 0:
        raise KeyError(f"unknown job_id: {job_id}")


def count_applied_today(conn: sqlite3.Connection, *, today: date | None = None) -> int:
    """Applications submitted on the current local calendar day (daily-cap query)."""
    day = (today or date.today()).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status = ? AND applied_at LIKE ?",
        (JobStatus.APPLIED.value, f"{day}%"),
    ).fetchone()
    return int(row[0])


def record_answer(conn: sqlite3.Connection, job_id: str, answer: Answer) -> None:
    """Insert or replace the answer for one field of one job."""
    provenance = _coerce_provenance(answer.provenance)
    conn.execute(
        """
        INSERT INTO answers (job_id, field, value, provenance, confidence)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(job_id, field) DO UPDATE SET
            value      = excluded.value,
            provenance = excluded.provenance,
            confidence = excluded.confidence
        """,
        (job_id, answer.field, answer.value, provenance.value, answer.confidence),
    )


def get_answers(conn: sqlite3.Connection, job_id: str) -> list[Answer]:
    rows = conn.execute(
        "SELECT field, value, provenance, confidence FROM answers WHERE job_id = ? "
        "ORDER BY field",
        (job_id,),
    ).fetchall()
    return [
        Answer(
            field=row["field"],
            value=row["value"],
            provenance=Provenance(row["provenance"]),
            confidence=row["confidence"],
        )
        for row in rows
    ]


def upsert_resume_index(conn: sqlite3.Connection, entry: ResumeIndexEntry) -> None:
    """Cache (or refresh) a resume's LLM-extracted role keywords by file hash."""
    conn.execute(
        """
        INSERT INTO resume_index (file_hash, file_path, role_keywords, indexed_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(file_hash) DO UPDATE SET
            file_path     = excluded.file_path,
            role_keywords = excluded.role_keywords,
            indexed_at    = excluded.indexed_at
        """,
        (
            entry.file_hash,
            entry.file_path,
            json.dumps(list(entry.role_keywords)),
            _now_iso(),
        ),
    )


def get_resume_index(
    conn: sqlite3.Connection, file_hash: str
) -> ResumeIndexEntry | None:
    row = conn.execute(
        "SELECT file_hash, file_path, role_keywords FROM resume_index WHERE file_hash = ?",
        (file_hash,),
    ).fetchone()
    if row is None:
        return None
    return ResumeIndexEntry(
        file_hash=row["file_hash"],
        file_path=row["file_path"],
        role_keywords=tuple(json.loads(row["role_keywords"])),
    )
