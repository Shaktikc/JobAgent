"""`session` — Playwright browser lifecycle and the dedicated persistent profile.

Implemented in Task 3. Owns launching the browser on ``data/profile`` and the
manual-login flow. No other module may launch a browser, and the everyday Chrome
profile is never touched (SPEC.md §8).
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from playwright.sync_api import BrowserContext, Page, sync_playwright

from src.configuration import AppSettings, SessionSettings
from src.tools import linkedin


def build_context_options(session: SessionSettings) -> dict[str, Any]:
    """Translate session config into Playwright persistent-context keyword args.

    Pure: no browser is launched, so this is unit-testable without Playwright
    (SPEC.md §6). The user-agent and viewport come from configuration only — they
    are never hardcoded here (SPEC.md §8).
    """
    options: dict[str, Any] = {
        "user_agent": session.user_agent,
        "viewport": {
            "width": session.viewport.width,
            "height": session.viewport.height,
        },
        "locale": session.locale,
        "headless": session.headless,
    }
    if session.slow_mo_ms:
        options["slow_mo"] = session.slow_mo_ms
    if session.timezone_id:
        options["timezone_id"] = session.timezone_id
    return options


@contextmanager
def browser_context(settings: AppSettings) -> Iterator[BrowserContext]:
    """Launch the dedicated persistent Chromium profile — the only browser entry point.

    ``data/profile`` is the Chromium user-data directory, so cookies persist across
    process restarts and a second run reuses the stored LinkedIn session.
    """
    settings.paths.ensure_runtime_dirs()
    options = build_context_options(settings.session)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(settings.paths.profile),
            **options,
        )
        context.set_default_navigation_timeout(settings.session.navigation_timeout_ms)
        try:
            yield context
        finally:
            context.close()


def _first_page(context: BrowserContext) -> Page:
    return context.pages[0] if context.pages else context.new_page()


def login(settings: AppSettings) -> int:
    """Open the browser, ensure a LinkedIn session, and persist it (criterion 1).

    Manual login only — credentials are never automated (SPEC.md §8). On a second
    run the stored profile is already authenticated, so nothing is prompted.
    """
    with browser_context(settings) as context:
        page = _first_page(context)
        page.goto(linkedin.FEED_URL, wait_until="domcontentloaded")

        if linkedin.is_logged_in(page):
            print("LinkedIn session reused from data/profile; nothing to do.")
            return 0

        print(
            "Not logged in. Log in to LinkedIn in the open browser window; "
            f"waiting up to {settings.session.login_timeout_seconds}s."
        )
        if linkedin.wait_for_login(page, settings.session.login_timeout_seconds):
            print("Login detected; session saved to data/profile.")
            return 0

        print(
            "Timed out waiting for LinkedIn login. Run `login` again to retry.",
            file=sys.stderr,
        )
        return 1
