"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

import subprocess

import pytest

from src.configuration import SessionSettings, Settings
from src.tools import browser as browser_tools
from src.tools.linkedin import build_jobs_search_url

from .helpers import (
    _settings,
)

SEARCH_URL = build_jobs_search_url("software engineer")


def test_build_browser_creates_profile_dir(tmp_path) -> None:
    pytest.importorskip("browser_use")
    settings = _settings(tmp_path, headless=True)
    browser = browser_tools.build_browser(settings)
    assert browser is not None
    assert settings.profile_dir.is_dir()


def test_clear_profile_locks_removes_singleton_files(tmp_path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    for name in browser_tools._PROFILE_LOCK_FILES:
        (profile / name).write_text("x", encoding="utf-8")
    assert browser_tools._profile_is_locked(profile) is True

    browser_tools._clear_profile_locks(profile)

    assert browser_tools._profile_is_locked(profile) is False
    assert all(not (profile / name).exists() for name in browser_tools._PROFILE_LOCK_FILES)


def test_clean_profile_terminates_and_unlocks(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    settings = Settings(session=SessionSettings(headless=True), data_dir=tmp_path)
    settings.profile_dir.mkdir(parents=True)
    (settings.profile_dir / "lockfile").write_text("", encoding="utf-8")
    calls: list = []

    def fake_terminate(profile_dir):
        calls.append(profile_dir)
        return 2

    monkeypatch.setattr(browser_tools, "terminate_profile_browsers", fake_terminate)

    killed = browser_tools.clean_profile(settings)

    assert killed == 2
    assert calls == [settings.profile_dir]
    assert browser_tools._profile_is_locked(settings.profile_dir) is False


def test_terminate_profile_browsers_kills_each_pid(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(browser_tools, "_profile_browser_pids", lambda _p: [11, 22])
    commands: list = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(browser_tools.subprocess, "run", fake_run)

    assert browser_tools.terminate_profile_browsers(tmp_path) == 2
    assert len(commands) == 2


def test_build_browser_clears_a_stale_profile_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    pytest.importorskip("browser_use")
    settings = Settings(
        session=SessionSettings(headless=True, clean_stale_profile=True),
        data_dir=tmp_path,
    )
    settings.profile_dir.mkdir(parents=True)
    (settings.profile_dir / "lockfile").write_text("", encoding="utf-8")

    # No live browser owns the lock, so it is stale and may be cleared.
    monkeypatch.setattr(browser_tools, "_profile_browser_pids", lambda _p: [])

    browser = browser_tools.build_browser(settings)

    assert browser is not None
    assert browser_tools._profile_is_locked(settings.profile_dir) is False


def test_build_browser_refuses_to_kill_a_live_browser_holding_the_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A second launch must not tear down a browser another run is driving.

    Regression test for the reported failure: force-closing the live browser
    dropped its CDP WebSocket and every reconnect was refused (WinError 1225).
    """
    pytest.importorskip("browser_use")
    settings = Settings(
        session=SessionSettings(headless=True, clean_stale_profile=True),
        data_dir=tmp_path,
    )
    settings.profile_dir.mkdir(parents=True)
    (settings.profile_dir / "lockfile").write_text("", encoding="utf-8")

    # A live browser owns the profile (a running process references it).
    monkeypatch.setattr(browser_tools, "_profile_browser_pids", lambda _p: [4321])
    killed: list = []

    def fake_terminate(profile_dir):
        killed.append(profile_dir)
        return 1

    monkeypatch.setattr(browser_tools, "terminate_profile_browsers", fake_terminate)

    with pytest.raises(RuntimeError, match="already using the AutoJobApply profile"):
        browser_tools.build_browser(settings)

    # The live browser was left untouched, so the other run keeps its CDP link.
    assert killed == []
    assert browser_tools._profile_is_locked(settings.profile_dir) is True


def test_build_browser_skips_cleanup_when_profile_is_free(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    pytest.importorskip("browser_use")
    settings = Settings(session=SessionSettings(headless=True), data_dir=tmp_path)
    calls: list = []

    def fake_terminate(profile_dir):
        calls.append(profile_dir)
        return 0

    monkeypatch.setattr(browser_tools, "terminate_profile_browsers", fake_terminate)

    browser = browser_tools.build_browser(settings)

    assert browser is not None
    assert calls == []
