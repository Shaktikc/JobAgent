"""`session` — browser-use lifecycle on the dedicated persistent profile.

Rewritten in Task 17 (ADR 0001): browser-use owns the browser, launched on
``data/profile`` so a manual LinkedIn login persists across runs. The everyday
Chrome profile is never touched (SPEC.md §8).

No other module may launch a browser. ``build_launch_options`` is pure and
unit-testable without launching anything.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from src.configuration import AppSettings, SessionSettings
from src.tools import linkedin
from src.tools.browser_agent import BrowserUseNotInstalledError


def build_launch_options(session: SessionSettings, profile: Path) -> dict[str, Any]:
    """Translate session config into browser-use ``Browser`` keyword arguments.

    Pure: no browser is launched, so this is unit-testable (SPEC.md §6). The
    user-agent and viewport come from configuration only — never hardcoded here
    (SPEC.md §8).
    """
    return {
        "user_data_dir": str(profile),
        "headless": session.headless,
        "user_agent": session.user_agent,
        "viewport": {
            "width": session.viewport.width,
            "height": session.viewport.height,
        },
    }


def build_browser(settings: AppSettings) -> Any:
    """Construct (but do not start) the browser-use session on ``data/profile``."""
    try:
        from browser_use import Browser
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        raise BrowserUseNotInstalledError() from exc

    return Browser(**build_launch_options(settings.session, settings.paths.profile))


@asynccontextmanager
async def browser_session(settings: AppSettings) -> AsyncIterator[Any]:
    """Start the dedicated persistent browser for the duration of a run."""
    settings.paths.ensure_runtime_dirs()
    browser = build_browser(settings)
    await browser.start()
    try:
        yield browser
    finally:
        await browser.stop()


async def login(settings: AppSettings) -> int:
    """Open the browser, ensure a LinkedIn session, and persist it (criterion 1).

    Manual login only — credentials are never automated (SPEC.md §8). On a second
    run the stored profile is already authenticated, so nothing is prompted.
    """
    async with browser_session(settings) as browser:
        await browser.navigate_to(linkedin.FEED_URL)

        if linkedin.login_state_from_url(await browser.get_current_page_url()):
            print("LinkedIn session reused from data/profile; nothing to do.")
            return 0

        print(
            "Not logged in. Log in to LinkedIn in the open browser window; "
            f"waiting up to {settings.session.login_timeout_seconds}s."
        )
        if await linkedin.wait_for_login(browser, settings.session.login_timeout_seconds):
            print("Login detected; session saved to data/profile.")
            return 0

        print(
            "Timed out waiting for LinkedIn login. Run `login` again to retry.",
            file=sys.stderr,
        )
        return 1
