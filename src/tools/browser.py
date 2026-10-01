"""`session` — browser-use lifecycle on the dedicated persistent profile.

browser-use owns the browser, launched on
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
    """Translate session config into browser-use ``BrowserProfile`` keyword arguments.

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
        # Keep the browser alive across pipeline tasks. Without this, browser-use
        # kills the browser at the end of every ``agent.run()``, so the next task
        # (answer → fill) starts against a dead session and stalls (CP-B, 2026-09-30).
        "keep_alive": True,
        # Watchable mode: stream the agent's live log panel in the browser window
        # (needs headless=False) and pause a beat between each browser action so a
        # human can follow the flow. Both are driven from SessionSettings.
        "demo_mode": session.slow_mo_ms > 0,
        "wait_between_actions": max(session.slow_mo_ms, 100) / 1000.0,
    }


def build_browser(settings: AppSettings) -> Any:
    """Construct (but do not start) the browser-use session on ``data/profile``."""
    try:
        from browser_use import Browser, BrowserProfile
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        raise BrowserUseNotInstalledError() from exc

    # ``demo_mode``, ``keep_alive``, ``wait_between_actions`` are BrowserProfile
    # fields, so everything goes through a profile object rather than raw kwargs.
    options = build_launch_options(settings.session, settings.paths.profile)
    return Browser(browser_profile=BrowserProfile(**options))


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


# CDP-level read of the page's visible text. The arrow-function form is required
# by browser-use's ``Page.evaluate``.
_PAGE_TEXT_JS = "() => document.body.innerText"


async def read_page_text(browser: Any) -> str:
    """Return the visible text of the browser's current page.

    Uses a CDP-level ``Page.evaluate`` rather than ``Browser.get_state_as_text()``:
    in browser-use 0.13.10 the ``BrowserStateRequestEvent`` handler is only attached
    for the lifetime of an :class:`~browser_use.Agent` run, so ``get_state_as_text``
    raises ``ValueError`` once the agent has returned (found in the 2026-09-30 CP-B
    run). The CDP read works both before and after a run, which is what the guard's
    rate-limit check needs. Returns an empty string when there is no page.
    """
    page = await browser.get_current_page()
    if page is None:
        return ""
    text: str = await page.evaluate(_PAGE_TEXT_JS)
    return text


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
