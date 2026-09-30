"""Recovery + observability hooks for the browser-use agent (found in CP-B).

The 2026-09-30 real-browser CP-B run of job ``4468706364`` **stalled** after the
discover step. The cause chain:

1. An agent ``navigate`` action with a bare/malformed URL raises Chrome's
   ``Cannot navigate to invalid URL`` / ``Unsupported URL scheme``, and that
   navigation error leaves the browser session **stale** (the tab is gone).
2. Every later step then logs ``Cannot navigate - browser not connected`` and
   spins. The agent never recovers because it never treats a stale session as
   recoverable.
3. Worse, browser-use **kills the browser at the end of each ``agent.run()``
   unless ``keep_alive=True``**, so the session is already dead when the next
   pipeline task (answer → fill) starts.

This module exposes:

- :class:`StepLogger` — an ``on_step_end`` hook that prints one line per step so a
  human can watch the flow (the "slow, observable" mode).
- :func:`build_on_step_end` — the hook that runs after each step: logs, and if the
  session went stale (``browser is not connected``), re-``start()``s it so the
  next step has a live page instead of spinning.

Hooks are pure callables over an opaque agent object, so they are unit-testable
with a fake agent — no browser, no LLM.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


async def session_is_alive(browser: Any) -> bool:
    """True when the browser-use session still has a connected CDP client.

    A stale session (post-navigation failure) has ``_cdp_client_root is None``.
    Falls back to ``is_cdp_connected`` when that private attribute is absent.
    """
    connected = getattr(browser, "_cdp_client_root", None)
    if connected is not None:
        return True
    probe = getattr(browser, "is_cdp_connected", None)
    if callable(probe):
        return bool(probe())
    return False


async def recover_session(browser: Any) -> bool:
    """Re-attach a dead/stale browser-use session so the next step has a page.

    ``start()`` is what ``browser_session`` calls to stand the browser up; calling
    it again on a stale session re-establishes the CDP client and re-attaches the
    event handlers. Returns True when a recovery was attempted.
    """
    if await session_is_alive(browser):
        return False
    start = getattr(browser, "start", None)
    if callable(start):
        await start()
        return True
    return False


class StepLogger:
    """``on_step_end`` hook that prints the agent's progress one line at a time.

    Turned on by ``run_task(..., log=True)``. Uses an injectable ``out`` so tests
    capture the lines without touching stdout.
    """

    def __init__(self, out: Callable[[str], None] = print) -> None:
        self._out = out

    async def __call__(self, agent: Any) -> None:
        step = getattr(getattr(agent, "state", None), "n_steps", 0)
        url = ""
        browser = getattr(agent, "browser_session", None) or getattr(agent, "browser", None)
        if browser is not None:
            try:
                url = await browser.get_current_page_url()
            except Exception:  # noqa: BLE001 - observability must never break the run
                url = "(unknown)"
        self._out(f"[step {step}] {url}")


def build_on_step_end(
    *,
    logger: StepLogger | None = None,
    recover: bool = True,
) -> Callable[[Any], Awaitable[None]]:
    """Compose the ``on_step_end`` hook: optional logging + stale-session recovery."""

    async def on_step_end(agent: Any) -> None:
        if logger is not None:
            await logger(agent)
        if not recover:
            return
        browser = getattr(agent, "browser_session", None) or getattr(agent, "browser", None)
        if browser is not None:
            await recover_session(browser)

    return on_step_end
