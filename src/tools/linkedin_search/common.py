"""Shared Task 1 helpers.

``_settle_after_click`` is the one-control-at-a-time rule: after a click that can
re-render or navigate the results page, wait for ``post_click_wait_seconds`` and
then until ``document.readyState`` is ``'complete'`` before touching the next
control. Keeping it in one module lets the search bar and the filters share the
same behaviour.
"""

from __future__ import annotations

import asyncio

from src.configuration import Settings
from src.tools.browser import _wait_for_load


async def _settle_after_click(page, settings: Settings) -> None:
    """Wait for the page to finish loading after a click.

    The flow clicks **one** control at a time. A click can navigate or reload
    the page, so before the next control is touched the run pauses for
    ``post_click_wait_seconds`` (giving the navigation time to commit) and then
    waits until ``document.readyState`` is ``'complete'``. Without this the next
    step interacts with a half-loaded page, which shows up as several controls
    being clicked at once.
    """
    if settings.session.post_click_wait_seconds:
        await asyncio.sleep(settings.session.post_click_wait_seconds)
    await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)


__all__ = ["_settle_after_click"]
