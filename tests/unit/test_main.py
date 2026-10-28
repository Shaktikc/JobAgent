"""Unit tests for the CLI entry point (offline: no browser, no network)."""

from __future__ import annotations

import sys
import types

from src.configuration import SessionSettings, Settings
from src.main import (
    _UNLIMITED_SKIP_BUDGET,
    _parse_args,
    _recursion_limit,
    _silence_windows_pipe_noise,
)


def test_parse_args_defaults_to_dry_run() -> None:
    args = _parse_args([])
    assert args.dry_run is True
    assert args.clean_profile is False


def test_parse_args_no_dry_run() -> None:
    assert _parse_args(["--no-dry-run"]).dry_run is False


def test_parse_args_clean_profile_flag() -> None:
    assert _parse_args(["--clean-profile"]).clean_profile is True


def test_recursion_limit_budgets_skipped_jobs_too() -> None:
    # The jobs cap alone is not enough: strict matching may skip many jobs before
    # any is applied, so the graph needs room for those match -> next_job cycles.
    limited = Settings(
        session=SessionSettings(max_jobs_per_run=1, max_skipped_jobs_per_run=2)
    )
    unlimited_skips = Settings(
        session=SessionSettings(max_jobs_per_run=1, max_skipped_jobs_per_run=0)
    )

    assert _recursion_limit(limited) == 36 + 6
    # 0 means no skip cap, not "no skip budget"; otherwise a long unmatched scan
    # would fail on the graph recursion limit instead of running to exhaustion.
    assert _recursion_limit(unlimited_skips) == 36 + _UNLIMITED_SKIP_BUDGET


def test_silences_only_the_closed_pipe_unraisable(monkeypatch) -> None:
    """Only the harmless Windows shutdown error is swallowed; others pass through."""
    monkeypatch.setattr(sys, "platform", "win32")
    forwarded: list = []
    monkeypatch.setattr(sys, "unraisablehook", lambda unraisable: forwarded.append(unraisable))

    _silence_windows_pipe_noise()
    hook = sys.unraisablehook

    ignored = types.SimpleNamespace(exc_value=ValueError("I/O operation on closed pipe"))
    hook(ignored)
    assert forwarded == []

    other = types.SimpleNamespace(exc_value=ValueError("something else"))
    hook(other)
    assert forwarded == [other]


def test_silence_is_a_noop_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    original = sys.unraisablehook

    _silence_windows_pipe_noise()

    assert sys.unraisablehook is original


def test_summary_includes_strict_resume_skips() -> None:
    from src.main import _summary
    from src.state import ApplyState, SkippedJobRecord, Task16Outcome

    state = ApplyState(
        status="done",
        task16=Task16Outcome(
            enabled=True,
            jobs_skipped=1,
            skipped=[
                SkippedJobRecord(
                    title="Data Analyst",
                    company="Acme",
                    fit="partial",
                    rationale="not a strong match",
                )
            ],
        ),
    )

    summary = _summary(state)

    assert "resume gate : strict=True jobs_skipped=1" in summary
    assert "'Data Analyst' at 'Acme'" in summary
    assert "fit=partial" in summary
    assert "not a strong match" in summary


def test_summary_includes_task8_loop_results() -> None:
    from src.main import _summary
    from src.state import ApplyState, Task8JobRecord, Task8Outcome

    state = ApplyState(
        status="done",
        url="https://www.linkedin.com/login/",
        search_query="software engineer",
        task8=Task8Outcome(
            iterations=2,
            jobs_applied=2,
            max_jobs=35,
            stopped_reason="every job on every results page is already Applied",
            jobs=[
                Task8JobRecord(
                    index=0,
                    title="Backend Engineer",
                    company="Acme",
                    resume_path="resumes/a.pdf",
                    outcome="submitted",
                ),
                Task8JobRecord(
                    index=1,
                    title="Data Engineer",
                    company="Acme",
                    resume_path="resumes/a.pdf",
                    outcome="submitted",
                ),
            ],
        ),
    )

    summary = _summary(state)

    assert "task 8" in summary
    assert "jobs_submitted=2" in summary
    assert "cap=35" in summary
    assert "every job on every results page is already Applied" in summary
    assert "Backend Engineer" in summary
    assert "Data Engineer" in summary
