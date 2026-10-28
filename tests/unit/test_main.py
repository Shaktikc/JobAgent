"""Unit tests for the CLI entry point (offline: no browser, no network)."""

from __future__ import annotations

import sys
import types

from src.main import _parse_args, _silence_windows_pipe_noise


def test_parse_args_defaults_to_dry_run() -> None:
    args = _parse_args([])
    assert args.dry_run is True
    assert args.clean_profile is False


def test_parse_args_no_dry_run() -> None:
    assert _parse_args(["--no-dry-run"]).dry_run is False


def test_parse_args_clean_profile_flag() -> None:
    assert _parse_args(["--clean-profile"]).clean_profile is True


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
