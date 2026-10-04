"""Unit tests for environment-backed configuration."""

from __future__ import annotations

import pathlib

import pytest

from src.configuration import SessionSettings, load_settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate tests from the developer's real .env and shell environment."""
    for name in list(__import__("os").environ):
        if name.startswith("AUTOJOB_"):
            monkeypatch.delenv(name, raising=False)
    # Point loading at a path that does not exist so the real .env is ignored.
    monkeypatch.setattr(
        "src.configuration.DEFAULT_ENV_FILE",
        pathlib.Path("__no_such_env_file__"),
    )


def test_defaults_are_safe() -> None:
    settings = load_settings()
    assert settings.session.headless is False
    assert settings.session.viewport == {"width": 1280, "height": 800}
    assert settings.session.navigation_timeout_ms == 60_000
    assert settings.session.login_timeout_seconds == 300
    assert settings.session.login_poll_seconds == 2.0
    assert settings.session.post_click_wait_seconds == 2.0
    assert settings.session.easy_apply_timeout_seconds == 20.0
    assert settings.session.step_delay_seconds == 0.0


def test_env_overrides_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOJOB_SESSION_HEADLESS", "true")
    monkeypatch.setenv("AUTOJOB_SESSION_VIEWPORT_WIDTH", "1440")
    monkeypatch.setenv("AUTOJOB_SESSION_NAVIGATION_TIMEOUT_MS", "30000")
    monkeypatch.setenv("AUTOJOB_SESSION_LOGIN_TIMEOUT_SECONDS", "600")
    monkeypatch.setenv("AUTOJOB_SESSION_LOGIN_POLL_SECONDS", "0.5")
    monkeypatch.setenv("AUTOJOB_SESSION_POST_CLICK_WAIT_SECONDS", "0.25")
    monkeypatch.setenv("AUTOJOB_SESSION_EASY_APPLY_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("AUTOJOB_SESSION_STEP_DELAY_SECONDS", "3")

    settings = load_settings()
    assert settings.session.headless is True
    assert settings.session.viewport["width"] == 1440
    assert settings.session.navigation_timeout_ms == 30_000
    assert settings.session.login_timeout_seconds == 600
    assert settings.session.login_poll_seconds == 0.5
    assert settings.session.post_click_wait_seconds == 0.25
    assert settings.session.easy_apply_timeout_seconds == 12.5
    assert settings.session.step_delay_seconds == 3.0


def test_data_dir_override(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("AUTOJOB_DATA_DIR", str(tmp_path))
    settings = load_settings()
    assert settings.data_dir == tmp_path
    assert settings.profile_dir == tmp_path / "profile"
    assert settings.debug_dir == tmp_path / "debug"


def test_default_dirs_are_under_data_dir() -> None:
    settings = load_settings()
    assert settings.profile_dir == settings.data_dir / "profile"
    assert settings.debug_dir == settings.data_dir / "debug"


def test_invalid_values_are_rejected() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SessionSettings(viewport_width=0)
    with pytest.raises(ValidationError):
        SessionSettings(navigation_timeout_ms=0)
    with pytest.raises(ValidationError):
        SessionSettings(login_timeout_seconds=0)
    with pytest.raises(ValidationError):
        SessionSettings(login_poll_seconds=0)
    with pytest.raises(ValidationError):
        SessionSettings(post_click_wait_seconds=-1)
    with pytest.raises(ValidationError):
        SessionSettings(easy_apply_timeout_seconds=0)
    with pytest.raises(ValidationError):
        SessionSettings(step_delay_seconds=-1)
