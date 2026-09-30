"""Unit tests for browser session configuration and login-state detection (Task 3).

No browser is launched here (SPEC.md §6): these tests exercise the pure
config-to-options mapping and the URL-based login predicate only.
"""

from __future__ import annotations

import pytest

from src.configuration import AppSettings, SessionSettings, Viewport
from src.tools import browser, linkedin

SESSION_ENV_KEYS = (
    "AUTOJOB_SESSION_USER_AGENT",
    "AUTOJOB_SESSION_HEADLESS",
    "AUTOJOB_SESSION_VIEWPORT_WIDTH",
    "AUTOJOB_SESSION_VIEWPORT_HEIGHT",
    "AUTOJOB_SESSION_LOCALE",
    "AUTOJOB_SESSION_TIMEZONE",
    "AUTOJOB_SESSION_LOGIN_TIMEOUT_SECONDS",
    "AUTOJOB_SESSION_NAVIGATION_TIMEOUT_MS",
)


@pytest.fixture(autouse=True)
def _clear_session_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in SESSION_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_session_defaults_are_configuration_not_hardcoded_in_browser() -> None:
    session = SessionSettings()

    assert session.user_agent.startswith("Mozilla/5.0")
    assert session.viewport == Viewport(width=1280, height=800)
    assert session.headless is False
    assert session.login_timeout_seconds > 0


def test_session_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOJOB_SESSION_USER_AGENT", "TestAgent/1.0")
    monkeypatch.setenv("AUTOJOB_SESSION_HEADLESS", "true")
    monkeypatch.setenv("AUTOJOB_SESSION_VIEWPORT_WIDTH", "1920")
    monkeypatch.setenv("AUTOJOB_SESSION_VIEWPORT_HEIGHT", "1080")
    monkeypatch.setenv("AUTOJOB_SESSION_LOCALE", "en-AU")

    session = SessionSettings.from_env()

    assert session.user_agent == "TestAgent/1.0"
    assert session.headless is True
    assert session.viewport.width == 1920
    assert session.viewport.height == 1080
    assert session.locale == "en-AU"


def test_context_options_carry_the_configured_identity() -> None:
    session = SessionSettings(
        user_agent="Agent/9",
        viewport=Viewport(width=1440, height=900),
    )

    options = browser.build_context_options(session)

    assert options["user_agent"] == "Agent/9"
    assert options["viewport"] == {"width": 1440, "height": 900}
    assert options["headless"] is False


def test_context_options_omit_timezone_when_unset() -> None:
    options = browser.build_context_options(SessionSettings(timezone_id=None))

    assert "timezone_id" not in options


def test_app_settings_expose_session() -> None:
    assert isinstance(AppSettings().session, SessionSettings)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/feed/",
        "https://www.linkedin.com/mynetwork/",
    ],
)
def test_login_state_true_for_authenticated_urls(url: str) -> None:
    assert linkedin.login_state_from_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/login",
        "https://www.linkedin.com/authwall?trk=guest_homepage",
        "https://www.linkedin.com/checkpoint/challenge/",
        "https://www.linkedin.com/uas/login",
    ],
)
def test_login_state_false_for_logged_out_urls(url: str) -> None:
    assert linkedin.login_state_from_url(url) is False
