"""Ordering and lifecycle regressions for the latest-activity panel."""

import asyncio

from src.tools.linkedin_status_overlay import _CLEAR_STATUS_JS, _UPDATE_STATUS_JS, StatusReporter


class Page:
    def __init__(self, block=False):
        self.calls = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        if not block:
            self.release.set()

    async def evaluate(self, js, *args):
        if js == _UPDATE_STATUS_JS:
            self.started.set()
            await self.release.wait()
        self.calls.append((js, args))


async def drain():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_burst_is_coalesced_and_latest_wins_while_update_is_in_flight():
    page, emitted = Page(block=True), []
    reporter = StatusReporter(emit=emitted.append, page=page)
    reporter("first")
    await page.started.wait()
    for i in range(100):
        reporter(f"job {i}")
    await drain()
    page.release.set()
    await drain()
    assert [args[1] for _, args in page.calls] == ["first", "job 99"]
    assert len(emitted) == 101


async def test_duplicates_do_not_render_but_still_print():
    page, emitted = Page(), []
    reporter = StatusReporter(emit=emitted.append, page=page)
    for _ in range(3):
        reporter("same")
        await drain()
    assert len(page.calls) == 1
    assert emitted == ["same"] * 3


async def test_clear_cancels_in_flight_and_pending_updates():
    page = Page(block=True)
    reporter = StatusReporter(page=page)
    reporter("first")
    await page.started.wait()
    reporter("pending")
    await reporter.clear()
    page.release.set()
    reporter("after cleanup")
    await drain()
    assert page.calls == [(_CLEAR_STATUS_JS, ())]


async def test_bind_replays_latest_message_and_rebind_renders_on_new_page():
    reporter = StatusReporter()
    reporter("before browser")
    for page in (Page(), Page()):
        reporter.bind_page(page)
        await drain()
        assert page.calls == [(_UPDATE_STATUS_JS, ("agent", "before browser"))]
    await reporter.clear()


async def test_bind_without_message_does_not_create_panel():
    page = Page()
    reporter = StatusReporter()
    reporter.bind_page(page)
    await drain()
    assert not page.calls
    await reporter.clear()


async def test_waiting_actor_and_cli_preserves_original_text():
    page, emitted = Page(), []
    reporter = StatusReporter(emit=emitted.append, page=page)
    message = "  Waiting for you\n\t- review sk-test12345"
    reporter(message)
    await drain()
    assert emitted == [message]
    assert page.calls == [(_UPDATE_STATUS_JS, ("waiting", "Waiting for you - review [redacted]"))]


def test_without_event_loop_keeps_cli_working():
    emitted = []
    reporter = StatusReporter(emit=emitted.append, page=Page())
    reporter("no loop")
    assert emitted == ["no loop"]


async def test_failed_evaluation_can_retry_the_same_message():
    class RecoveringPage(Page):
        async def evaluate(self, js, *args):
            if not self.started.is_set():
                self.started.set()
                raise RuntimeError("temporary disconnect")
            return await super().evaluate(js, *args)

    page = RecoveringPage()
    reporter = StatusReporter(page=page)
    reporter("latest")
    await drain()
    reporter("latest")
    await drain()
    assert page.calls == [(_UPDATE_STATUS_JS, ("agent", "latest"))]


async def test_in_flight_duplicate_cannot_hide_a_newer_value():
    page = Page(block=True)
    reporter = StatusReporter(page=page)
    reporter("A")
    await page.started.wait()
    reporter("B")
    reporter("A")
    page.release.set()
    await drain()
    assert page.calls == [(_UPDATE_STATUS_JS, ("agent", "A"))]
