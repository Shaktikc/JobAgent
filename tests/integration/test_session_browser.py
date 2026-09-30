"""Integration smoke for the browser-use session (Task 3, rewritten in Task 17).

Marked ``integration``: launches the real browser on a throwaway persistent
profile. Never runs in CI (SPEC.md §6). No LinkedIn login is required — the manual
login-twice check is separate and human-driven.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.configuration import AppSettings, Paths, SessionSettings, Viewport
from src.tools import browser

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
    )

    async def go() -> None:
        async with browser.browser_session(settings) as session:
            await session.navigate_to("about:blank")
            page = await session.get_current_page()
            assert page is not None
            assert await page.evaluate("navigator.userAgent") == "AutoJobApply-Test/1.0"
            assert await page.evaluate("window.innerWidth") == 802

    asyncio.run(go())
    assert settings.paths.profile.is_dir()


def test_a_second_session_reuses_the_same_profile(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    async def go() -> None:
        async with browser.browser_session(settings) as session:
            await session.navigate_to("about:blank")
        async with browser.browser_session(settings) as session:
            await session.navigate_to("about:blank")
            assert await session.get_current_page_url() in {"about:blank", ""}

    asyncio.run(go())
