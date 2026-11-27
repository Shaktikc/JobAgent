"""Mirror runtime logs to the CLI and a best-effort latest-activity panel."""

from __future__ import annotations

import asyncio
import contextlib

from src.tools.crash_logs import note_line
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
from src.tools.linkedin_status_overlay.panel_text import sanitize_panel_text

from .metrics_js import UPDATE_METRICS_JS


class StatusReporter:
    """Callable CLI callback with serialized, coalesced panel updates."""

    def __init__(self, emit=None, page=None) -> None:
        self.emit = emit or (lambda _message: None)
        self._page = page
        self._lock_task: asyncio.Task | None = None
        self._pump_task: asyncio.Task | None = None
        self._pending: tuple[str, str] | None = None
        self._latest: tuple[str, str] | None = None
        self._rendered = None
        self._closed = False
        self._metrics = getattr(self, "_metrics", ("", ""))

    def bind_page(self, page) -> None:
        """Attach the live page and install the automation interaction lock."""
        self._page = page
        from src.tools.token_usage import runtime as usage_runtime

        usage_runtime.reporter = self
        self._closed = False
        self._metrics = getattr(self, "_metrics", ("", ""))
        self._rendered = None
        if self._latest is not None:
            self._update(*self._latest)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # CLI-only reporter; no page task to schedule
        self._lock_task = loop.create_task(ensure_interaction_lock(page))

    def __call__(self, message: str) -> None:
        """Mirror a runtime log line without changing the CLI output."""
        self.emit(message)
        note_line(message)  # Task 33 run-log fallback when no stdout tee exists
        self._update("agent", message)

    def step(self, message: str) -> None:
        """Plain-language agent step: printed and shown on the page."""
        self.emit(message)
        note_line(message)
        self._update("agent", message)

    def llm(self, action: str, detail: str = "") -> None:
        """An LLM action/decision: printed and shown on the page, marked as LLM."""
        text = _format_llm(action, detail)
        self.emit(text)
        note_line(text)
        self._update("llm", text)

    def _update(self, actor: str, message: str) -> None:
        message = sanitize_panel_text(message)
        if message.startswith("Waiting for you"):
            actor = "waiting"
        self._latest = (actor, message)
        if self._closed or self._page is None or not message:
            return
        self._pending = self._latest
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # CLI-only; never block for a panel update
        if self._pump_task is None or self._pump_task.done():
            self._pump_task = loop.create_task(self._pump())

    def metrics(self, live: str, frozen: str = "") -> None:
        self._metrics = (live, frozen)
        self._rendered = None
        self._update(*(self._latest or ("agent", "Session started")))

    async def _pump(self) -> None:
        while self._pending is not None and not self._closed:
            value, self._pending = self._pending, None
            page = self._page
            if page is None or self._rendered == (page, value):
                continue
            try:
                await page.evaluate(_UPDATE_STATUS_JS, *value)
                if self._metrics[0]:
                    await page.evaluate(UPDATE_METRICS_JS, *self._metrics)
            except Exception:  # noqa: BLE001 - best-effort panel, CLI still works
                continue
            self._rendered = (page, value)

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
        self._closed = True
        self._pending = self._latest = self._rendered = None
        pump, self._pump_task = self._pump_task, None
        if pump is not None:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
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
