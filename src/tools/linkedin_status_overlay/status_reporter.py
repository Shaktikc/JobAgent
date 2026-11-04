"""Task 9: push agent/LLM status to the CLI and the on-page panel.

:class:`StatusReporter` is created in :func:`src.tools.browser.start_tasks` (as
soon as the page exists) and stored on the run, so later modules reach it via
``get_reporter(run_id)``. It wraps the existing CLI ``notify`` callback: calling
the reporter still prints to the CLI exactly as before, while :meth:`step` and
:meth:`llm` additionally update the on-page panel. The module-level
:func:`emit_step` / :func:`emit_llm` helpers work whether the status object is a
full reporter or a plain ``notify`` callable, so existing test fakes keep working.

Split out of :mod:`src.tools.linkedin_status_overlay` so each module stays small;
the package re-exports the public names.
"""

from __future__ import annotations

import asyncio
import contextlib

from src.tools.linkedin_status_overlay.interaction_lock import (
    _RELEASE_TIMEOUT_SECONDS,
    _finish_cleanup,
    ensure_interaction_lock,
    release_interaction_lock,
)
from src.tools.linkedin_status_overlay.panel_js import (
    _CLEAR_STATUS_JS,
    _UPDATE_STATUS_JS,
    _format_llm,
)


class StatusReporter:
    """Pushes agent/LLM status to the CLI and the on-page panel (Task 9).

    The reporter is **callable**, so it can stand in anywhere the old
    ``progress``/``notify`` callback was passed; calling it prints to the CLI only
    (technical detail), while :meth:`step` and :meth:`llm` also update the panel
    with plain-language, human-facing text.
    """

    def __init__(self, emit=None, page=None) -> None:
        self.emit = emit or (lambda _message: None)
        self._page = page
        self._lock_task: asyncio.Task | None = None

    def bind_page(self, page) -> None:
        """Attach the live page and install the automation interaction lock."""
        self._page = page
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # CLI-only reporter; no page task to schedule
        self._lock_task = loop.create_task(ensure_interaction_lock(page))

    def __call__(self, message: str) -> None:
        """Technical notify line: CLI only (matches the old ``notify`` callback)."""
        self.emit(message)

    def step(self, message: str) -> None:
        """Plain-language agent step: printed and shown on the page."""
        self.emit(message)
        self._update("agent", message)

    def llm(self, action: str, detail: str = "") -> None:
        """An LLM action/decision: printed and shown on the page, marked as LLM."""
        text = _format_llm(action, detail)
        self.emit(text)
        self._update("llm", text)

    def _update(self, actor: str, message: str) -> None:
        page = self._page
        if page is None or not message:
            return
        self._schedule(page, _UPDATE_STATUS_JS, actor, message)

    def _schedule(self, page, js: str, *args) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no event loop: CLI-only, never block the caller
        loop.create_task(self._evaluate(page, js, *args))

    async def _evaluate(self, page, js: str, *args) -> None:
        try:
            await page.evaluate(js, *args)
        except Exception:  # noqa: BLE001 - the panel is best-effort feedback
            pass

    async def release_input(self) -> None:
        """Drain installation before the final handoff can release the lock."""
        page, pending = self._page, self._lock_task

        async def release():
            if pending is not None:
                # Cancel an unresponsive installer before it can outlive handoff.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        asyncio.gather(pending, return_exceptions=True),
                        _RELEASE_TIMEOUT_SECONDS,
                    )
            await release_interaction_lock(page)

        await _finish_cleanup(release())

    async def clear(self) -> None:
        """Remove the panel from the page (called once the run ends)."""
        page = self._page
        if page is None:
            return
        try:
            await self.release_input()
            await page.evaluate(_CLEAR_STATUS_JS)
        except Exception:  # noqa: BLE001 - nothing to clean up if the page is gone
            pass
        finally:
            self._page = None


def emit_step(status, message: str) -> None:
    """Emit an agent step through a reporter, or a plain ``notify`` callable."""
    if status is None or not message:
        return
    step = getattr(status, "step", None)
    if callable(step):
        step(message)
    elif callable(status):
        status(message)


def emit_llm(status, action: str, detail: str = "") -> None:
    """Emit an LLM action through a reporter, or a plain ``notify`` callable."""
    if status is None:
        return
    llm = getattr(status, "llm", None)
    if callable(llm):
        llm(action, detail)
    elif callable(status):
        status(_format_llm(action, detail))
