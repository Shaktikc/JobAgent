"""Unit tests for Task 9's on-page status panel and reporter (no real browser)."""

from __future__ import annotations

import asyncio

from src.tools import linkedin_status_overlay as status


class _FakePage:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, tuple]] = []

    async def evaluate(self, js: str, *args):
        if self.fail:
            raise RuntimeError("page is gone")
        self.calls.append((js, args))
        return True


async def _drain() -> None:
    """Let the reporter's fire-and-forget panel update run."""
    for _ in range(3):
        await asyncio.sleep(0)


def _reporter(page, emitted: list[str]) -> status.StatusReporter:
    return status.StatusReporter(emit=emitted.append, page=page)


async def test_step_prints_and_updates_the_panel() -> None:
    page = _FakePage()
    emitted: list[str] = []
    reporter = _reporter(page, emitted)

    reporter.step("Please wait - searching for 'software engineer' jobs...")
    await _drain()

    assert emitted == ["Please wait - searching for 'software engineer' jobs..."]
    assert len(page.calls) == 1
    js, args = page.calls[0]
    assert js == status._UPDATE_STATUS_JS
    assert args == ("agent", emitted[0])


async def test_llm_is_prefixed_and_marked_as_the_llm() -> None:
    page = _FakePage()
    emitted: list[str] = []
    reporter = _reporter(page, emitted)

    reporter.llm("summarizing resume 'cv.pdf'", "a backend profile")
    await _drain()

    assert emitted == ["LLM: summarizing resume 'cv.pdf' - a backend profile"]
    _js, args = page.calls[0]
    assert args[0] == "llm"
    assert args[1] == emitted[0]


async def test_call_is_cli_only_not_the_panel() -> None:
    page = _FakePage()
    emitted: list[str] = []
    reporter = _reporter(page, emitted)

    reporter("Task 2: 12 job(s) in the list.")
    await _drain()

    assert emitted == ["Task 2: 12 job(s) in the list."]
    assert page.calls == []  # technical detail does not clutter the panel


async def test_clear_removes_the_panel() -> None:
    page = _FakePage()
    reporter = _reporter(page, [])

    await reporter.clear()

    assert page.calls == [(status._CLEAR_STATUS_JS, ())]
    # Clearing twice is a no-op: the page is already detached.
    await reporter.clear()
    assert len(page.calls) == 1


async def test_step_survives_a_failing_page() -> None:
    page = _FakePage(fail=True)
    emitted: list[str] = []
    reporter = _reporter(page, emitted)

    reporter.step("Please wait - opening the Easy Apply form...")
    await _drain()

    assert emitted  # the CLI line still happened
    assert page.calls == []


async def test_no_page_is_cli_only() -> None:
    emitted: list[str] = []
    reporter = status.StatusReporter(emit=emitted.append)

    reporter.step("Please wait - starting the browser...")
    reporter.llm("choosing the best-matching resume", "picked one")
    await _drain()

    assert len(emitted) == 2


def test_emit_step_with_a_plain_notify_callable() -> None:
    seen: list[str] = []
    status.emit_step(seen.append, "Please wait - reading the job list...")
    assert seen == ["Please wait - reading the job list..."]


def test_emit_llm_with_a_plain_notify_callable() -> None:
    seen: list[str] = []
    status.emit_llm(seen.append, "classifying the question 'City'", "a location")
    assert seen == ["LLM: classifying the question 'City' - a location"]


def test_emit_helpers_accept_none() -> None:
    # A missing status must never raise.
    status.emit_step(None, "x")
    status.emit_llm(None, "x")


async def test_emit_llm_uses_the_reporter_panel() -> None:
    page = _FakePage()
    emitted: list[str] = []
    reporter = _reporter(page, emitted)

    status.emit_llm(reporter, "answered 'City'", "'Sydney' (location)")
    await _drain()

    assert emitted == ["LLM: answered 'City' - 'Sydney' (location)"]
    _js, args = page.calls[0]
    assert args[0] == "llm"
