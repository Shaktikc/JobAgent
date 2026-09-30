"""Integration smoke for the browser session (Task 3).

Marked ``integration``: launches the real Chromium on a throwaway persistent
profile. Never runs in CI (SPEC.md §6). No LinkedIn login is required — the
manual login-twice check is separate and human-driven.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.configuration import AppSettings, Paths, SessionSettings, Viewport
from src.tools.browser import browser_context

pytestmark = pytest.mark.integration


def _settings(root: Path, **session_overrides: object) -> AppSettings:
    data = root / "data"
    return AppSettings(
        paths=Paths(
            root=root,
            config=root / "config",
            resumes=root / "resumes",
            data=data,
            db=data / "autojobapply.db",
            profile=data / "profile",
            artifacts=data / "artifacts",
            stop=data / "STOP",
        ),
        session=SessionSettings(headless=True, **session_overrides),
    )


def test_persistent_profile_uses_the_configured_identity(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        user_agent="AutoJobApply-Test/1.0",
        viewport=Viewport(width=802, height=602),
        locale="en-GB",
    )

    with browser_context(settings) as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("about:blank")
        assert page.evaluate("navigator.userAgent") == "AutoJobApply-Test/1.0"
        assert page.evaluate("window.innerWidth") == 802
        assert page.evaluate("navigator.language") == "en-GB"

    assert settings.paths.profile.is_dir()


def test_authenticated_cookies_survive_a_browser_restart(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    with browser_context(settings) as context:
        context.add_cookies(
            [
                {
                    "name": "sid",
                    "value": "persisted",
                    "domain": "example.com",
                    "path": "/",
                    "expires": time.time() + 3600,
                }
            ]
        )

    with browser_context(settings) as context:
        cookies = {c["name"]: c["value"] for c in context.cookies("https://example.com")}

    assert cookies.get("sid") == "persisted"
