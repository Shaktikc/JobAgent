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
    assert settings.session.ai_search_timeout_seconds == 5.0
    assert settings.session.step_delay_seconds == 0.0
    assert settings.session.ask_human is True
    assert settings.session.ask_timeout_seconds == 300.0
    assert settings.session.ask_poll_seconds == 1.0
    assert settings.session.clean_stale_profile is True
    assert settings.session.skip_applied is True
    # Task 16: strict resume matching is the default, with a skip cap.
    assert settings.session.require_resume_match is True
    assert settings.session.max_skipped_jobs_per_run == 100
    assert settings.session.max_jobs_per_run == 35
    assert settings.self_healing.enabled is True
    assert settings.self_healing.max_repair_attempts == 3
    assert settings.self_healing.repair_command is None
    assert settings.self_healing.test_command is None


def test_env_overrides_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOJOB_SESSION_HEADLESS", "true")
    monkeypatch.setenv("AUTOJOB_SESSION_VIEWPORT_WIDTH", "1440")
    monkeypatch.setenv("AUTOJOB_SESSION_NAVIGATION_TIMEOUT_MS", "30000")
    monkeypatch.setenv("AUTOJOB_SESSION_LOGIN_TIMEOUT_SECONDS", "600")
    monkeypatch.setenv("AUTOJOB_SESSION_LOGIN_POLL_SECONDS", "0.5")
    monkeypatch.setenv("AUTOJOB_SESSION_POST_CLICK_WAIT_SECONDS", "0.25")
    monkeypatch.setenv("AUTOJOB_SESSION_EASY_APPLY_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("AUTOJOB_SESSION_AI_SEARCH_TIMEOUT_SECONDS", "0")
    monkeypatch.setenv("AUTOJOB_SESSION_STEP_DELAY_SECONDS", "3")
    monkeypatch.setenv("AUTOJOB_SESSION_ASK_HUMAN", "false")
    monkeypatch.setenv("AUTOJOB_SESSION_ASK_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("AUTOJOB_SESSION_ASK_POLL_SECONDS", "0.25")
    monkeypatch.setenv("AUTOJOB_SESSION_CLEAN_STALE_PROFILE", "false")
    monkeypatch.setenv("AUTOJOB_SESSION_SKIP_APPLIED", "false")
    monkeypatch.setenv("AUTOJOB_SESSION_REQUIRE_RESUME_MATCH", "false")
    monkeypatch.setenv("AUTOJOB_SESSION_MAX_SKIPPED_JOBS", "7")
    monkeypatch.setenv("AUTOJOB_SESSION_MAX_JOBS", "3")
    monkeypatch.setenv("AUTOJOB_SELF_HEAL_ENABLED", "false")
    monkeypatch.setenv("AUTOJOB_SELF_HEAL_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("AUTOJOB_SELF_HEAL_REPAIR_COMMAND", "repair --bundle")
    monkeypatch.setenv("AUTOJOB_SELF_HEAL_TEST_COMMAND", "pytest")
    monkeypatch.setenv("AUTOJOB_SELF_HEAL_COMMAND_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("AUTOJOB_SELF_HEAL_CLOSE_TIMEOUT_SECONDS", "5")

    settings = load_settings()
    assert settings.session.headless is True
    assert settings.session.viewport["width"] == 1440
    assert settings.session.navigation_timeout_ms == 30_000
    assert settings.session.login_timeout_seconds == 600
    assert settings.session.login_poll_seconds == 0.5
    assert settings.session.post_click_wait_seconds == 0.25
    assert settings.session.easy_apply_timeout_seconds == 12.5
    assert settings.session.ai_search_timeout_seconds == 0.0
    assert settings.session.step_delay_seconds == 3.0
    assert settings.session.ask_human is False
    assert settings.session.ask_timeout_seconds == 30.0
    assert settings.session.ask_poll_seconds == 0.25
    assert settings.session.clean_stale_profile is False
    assert settings.session.skip_applied is False
    assert settings.session.require_resume_match is False
    assert settings.session.max_skipped_jobs_per_run == 7
    assert settings.session.max_jobs_per_run == 3
    assert settings.self_healing.enabled is False
    assert settings.self_healing.max_repair_attempts == 2
    assert settings.self_healing.repair_command == "repair --bundle"
    assert settings.self_healing.test_command == "pytest"
    assert settings.self_healing.command_timeout_seconds == 30.0
    assert settings.self_healing.close_timeout_seconds == 5.0


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


def test_resumes_dir_default_and_override(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    assert load_settings().resumes_dir.name == "resumes"

    monkeypatch.setenv("AUTOJOB_RESUMES_DIR", str(tmp_path))
    assert load_settings().resumes_dir == tmp_path


def test_new_resumes_dir_default_and_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    settings = load_settings()
    assert settings.new_resumes_dir == settings.resumes_dir / "new"

    monkeypatch.setenv("AUTOJOB_RESUMES_DIR", str(tmp_path / "pool"))
    assert load_settings().new_resumes_dir == tmp_path / "pool" / "new"

    monkeypatch.setenv("AUTOJOB_NEW_RESUMES_DIR", str(tmp_path / "intake"))
    assert load_settings().new_resumes_dir == tmp_path / "intake"


def test_answers_file_default_and_override(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    settings = load_settings()
    assert settings.answers_file == settings.data_dir / "answers.json"

    custom = tmp_path / "custom-answers.json"
    monkeypatch.setenv("AUTOJOB_ANSWERS_FILE", str(custom))
    assert load_settings().answers_file == custom


def test_derived_answers_file_default_and_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    settings = load_settings()
    assert settings.derived_answers_file == settings.data_dir / "derived_answers.json"

    custom = tmp_path / "custom-derived.json"
    monkeypatch.setenv("AUTOJOB_DERIVED_ANSWERS_FILE", str(custom))
    assert load_settings().derived_answers_file == custom


def test_llm_settings_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("AUTOJOB_LLM_API_KEY", raising=False)
    assert load_settings().llm.configured is False

    monkeypatch.setenv("OPENROUTER_API_KEY", "secret")
    monkeypatch.setenv("AUTOJOB_LLM_MODEL", "deepseek/x")
    monkeypatch.setenv("AUTOJOB_LLM_TEMPERATURE", "0.5")
    monkeypatch.setenv("AUTOJOB_LLM_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("AUTOJOB_LLM_MAX_RETRIES", "1")
    monkeypatch.setenv("AUTOJOB_LLM_DISABLE_REASONING", "false")

    llm = load_settings().llm
    assert llm.configured is True
    assert llm.api_key == "secret"
    assert llm.model == "deepseek/x"
    assert llm.base_url == "https://openrouter.ai/api/v1"
    assert llm.temperature == 0.5
    assert llm.timeout_seconds == 30.0
    assert llm.max_retries == 1
    assert llm.disable_reasoning is False


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
        SessionSettings(ai_search_timeout_seconds=-1)
    with pytest.raises(ValidationError):
        SessionSettings(step_delay_seconds=-1)
    with pytest.raises(ValidationError):
        SessionSettings(ask_timeout_seconds=0)
    with pytest.raises(ValidationError):
        SessionSettings(ask_poll_seconds=0)
    with pytest.raises(ValidationError):
        SessionSettings(max_jobs_per_run=-1)
