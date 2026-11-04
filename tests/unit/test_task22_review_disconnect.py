"""An unresponsive CDP connection must not make review cleanup uninterruptible."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.tools.linkedin_status_overlay import interaction_lock as interaction
from src.tools.linkedin_status_overlay import status_reporter

_BUDGET = 0.03


class _Input:
    def __init__(self):
        self.ignored = False
        self.stall_unlock = False
        self.unlock_started = asyncio.Event()
        self.allow_unlock = asyncio.Event()
        self.writes = []

    async def setIgnoreInputEvents(self, params, session_id=None):
        if not params["ignore"] and self.stall_unlock:
            self.unlock_started.set()
            await self.allow_unlock.wait()
        self.ignored = params["ignore"]
        self.writes.append(self.ignored)

    async def dispatchMouseEvent(self, params, session_id=None):
        pass


class _Page:
    session_id = "disconnect-session"

    def __init__(self):
        self.input = _Input()
        self._client = SimpleNamespace(send=SimpleNamespace(Input=self.input))

    async def get_url(self):
        return "https://www.linkedin.com/jobs/view/123/"

    async def evaluate(self, *_):
        return False


class _StalledInstallationPage(_Page):
    def __init__(self):
        super().__init__()
        self.install_started = asyncio.Event()
        self.allow_install = asyncio.Event()

    @property
    def session_id(self):
        async def resolve():
            self.install_started.set()
            await self.allow_install.wait()
            return "disconnect-session"

        return resolve()


def _small_budget(monkeypatch):
    monkeypatch.setattr(interaction, "_RELEASE_TIMEOUT_SECONDS", _BUDGET, raising=False)
    monkeypatch.setattr(status_reporter, "_RELEASE_TIMEOUT_SECONDS", _BUDGET, raising=False)


async def _assert_bounded(task, cancel):
    if cancel:
        task.cancel()
    _, pending = await asyncio.wait({task}, timeout=0.3)
    assert not pending, "cleanup kept waiting for CDP after its release budget expired"
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await task


@pytest.mark.parametrize("cancel", [False, True])
async def test_unresponsive_unlock_finishes_cleanup_within_its_budget(monkeypatch, cancel):
    _small_budget(monkeypatch)
    page = _Page()
    original_mouse = page.input.dispatchMouseEvent
    lock = await interaction.ensure_interaction_lock(page)
    assert lock is not None
    assert page.input.ignored
    page.input.stall_unlock = True
    task = asyncio.create_task(interaction.release_interaction_lock(page))
    try:
        await asyncio.wait_for(page.input.unlock_started.wait(), 1)
        await _assert_bounded(task, cancel)
        assert page.input.dispatchMouseEvent == original_mouse
        assert lock._task is None or lock._task.done(), "the lock watcher survived cleanup"
        assert not lock._originals
        assert id(page) not in interaction._INTERACTION_LOCKS
    finally:
        # Let the pre-fix implementation unwind after the expected RED failure.
        page.input.allow_unlock.set()
        await asyncio.gather(task, return_exceptions=True)
        await interaction.release_interaction_lock(page)


@pytest.mark.parametrize("method", ["release_input", "clear"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_unresponsive_reporter_installation_cannot_hang_or_relock_after_cleanup(
    monkeypatch, method, cancel,
):
    _small_budget(monkeypatch)
    page = _StalledInstallationPage()
    reporter = status_reporter.StatusReporter()
    reporter.bind_page(page)
    pending_install = reporter._lock_task
    await asyncio.wait_for(page.install_started.wait(), 1)
    lock = interaction._INTERACTION_LOCKS[id(page)]
    task = asyncio.create_task(getattr(reporter, method)())
    try:
        # The installer is already blocked on its CDP session response. Cleanup
        # has to cancel/drain it, rather than waiting indefinitely for it.
        await asyncio.sleep(0)
        await _assert_bounded(task, cancel)
        assert pending_install.done(), "an abandoned installer can later re-lock review"
        assert lock._task is None or lock._task.done()
        assert id(page) not in interaction._INTERACTION_LOCKS
        writes_after_cleanup = list(page.input.writes)
        page.allow_install.set()
        await asyncio.sleep(0)
        assert page.input.writes == writes_after_cleanup, "installation continued after cleanup"
        assert not page.input.ignored
    finally:
        page.allow_install.set()
        page.input.allow_unlock.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.gather(pending_install, return_exceptions=True)
        await interaction.release_interaction_lock(page)
