"""Crash record and index-row shapes (Task 33).

Plain typed dictionaries (stdlib only) so the package imports before Pydantic or
the browser extras; ``crash.json`` follows :class:`CrashRecord`.
"""

from __future__ import annotations

from typing import Any, TypedDict

SCHEMA_VERSION = 1

CRASH_KINDS = (
    "uncaught_exception",
    "node_crash",
    "cleanup_crash",
    "submission_interrupted",
    "returned_failure",
    "startup_error",
    "cli_error",
    "interrupted",
    "thread_exception",
    "unraisable_exception",
    "asyncio_exception",
    "import_error",
)


class SelfHealingLink(TypedDict, total=False):
    bug_id: str
    bundle: str
    attempts: int
    recovered: bool


class CrashRecord(TypedDict, total=False):
    schema_version: int
    crash_id: str
    captured_at: str
    kind: str
    stage: str
    exit_code: int | None
    message: str
    run: dict[str, Any]
    exception: dict[str, Any]
    job: dict[str, Any]
    state: dict[str, Any]
    settings: dict[str, Any]
    run_log: dict[str, Any]
    browser: dict[str, Any]
    self_healing: SelfHealingLink
    context: dict[str, Any]
    errors: list[str]
    log: list[str]
    truncation: list[str]


class IndexRow(TypedDict, total=False):
    crash_id: str
    captured_at: str
    kind: str
    stage: str
    exception_type: str
    message: str
    job_title: str
    job_url: str
    bundle: str
    bug_id: str
    recovered: bool
    exit_code: int | None


def index_row(record: CrashRecord, bundle: str) -> IndexRow:
    exception = record.get("exception") or {}
    job = record.get("job") or {}
    healing = record.get("self_healing") or {}
    return IndexRow(
        crash_id=record.get("crash_id", ""),
        captured_at=record.get("captured_at", ""),
        kind=record.get("kind", ""),
        stage=record.get("stage", ""),
        exception_type=str(exception.get("type") or ""),
        message=str(exception.get("message") or record.get("message") or "")[:300],
        job_title=str(job.get("title") or ""),
        job_url=str(job.get("url") or ""),
        bundle=bundle,
        bug_id=str(healing.get("bug_id") or ""),
        recovered=bool(healing.get("recovered", False)),
        exit_code=record.get("exit_code"),
    )


__all__ = ["CRASH_KINDS", "SCHEMA_VERSION", "CrashRecord", "IndexRow", "index_row"]
