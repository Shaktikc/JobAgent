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
