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


def test_panel_never_intercepts_clicks() -> None:
    """The read-only panel must not swallow a click on the control beneath it.

    It is a top-layer popover with the maximum z-index, so without
    ``pointer-events:none`` it could sit over the Easy Apply footer's Next button
    and leave the form stuck (BUG-048).
    """
    assert "pointer-events:none" in status._UPDATE_STATUS_JS


class _FakeInput:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def setIgnoreInputEvents(self, params, session_id=None):
        self.calls.append(("ignore", params.get("ignore"), session_id))

    async def dispatchMouseEvent(self, params, session_id=None):
        self.calls.append(("mouse", session_id))

    async def dispatchKeyEvent(self, params, session_id=None):
        self.calls.append(("key", session_id))

    async def insertText(self, params, session_id=None):
        self.calls.append(("text", session_id))


class _SlowCommandInput(_FakeInput):
    """An Input client whose mouse dispatch blocks until the test releases it."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def dispatchMouseEvent(self, params, session_id=None):
        self.calls.append(("mouse", session_id))
        self.started.set()
        await self.release.wait()


class _FakeSend:
    def __init__(self, input_client) -> None:
        self.Input = input_client


class _FakeClient:
    def __init__(self, input_client) -> None:
        self.send = _FakeSend(input_client)


class _LockPage:
    def __init__(self, url: str = "https://www.linkedin.com/jobs/") -> None:
        self.input = _FakeInput()
        self._client = _FakeClient(self.input)
        self.session_id = "session-1"
        self.url = url

    async def get_url(self) -> str:
        return self.url

    async def evaluate(self, js: str, *args):
        return False


class _SlowInspectPage(_LockPage):
    """A page whose ``_on_login_page`` probe blocks until the test releases it."""

    def __init__(self) -> None:
        super().__init__()
        self.inspect_started = asyncio.Event()
        self.inspect_release = asyncio.Event()

    async def evaluate(self, js, *args):
        self.inspect_started.set()
        await self.inspect_release.wait()
        return False


class _SlowCommandPage(_LockPage):
    def __init__(self) -> None:
        super().__init__()
        self.input = _SlowCommandInput()
        self._client = _FakeClient(self.input)


async def test_interaction_lock_blocks_physical_input_but_not_automation() -> None:
    page = _LockPage()
    lock = await status.ensure_interaction_lock(page)
    assert lock is not None
    await asyncio.sleep(0)  # let install finish
    assert ("ignore", True, "session-1") in page.input.calls

    # Automation still works: the wrapper opens the lock for that one command.
    await page._client.send.Input.dispatchMouseEvent({"x": 1}, session_id="session-1")
    assert page.input.calls[-3:] == [
        ("ignore", False, "session-1"),
        ("mouse", "session-1"),
        ("ignore", True, "session-1"),
    ]

    await status.begin_human_turn(page)
    assert page.input.calls[-1] == ("ignore", False, "session-1")
    await status.end_human_turn(page)
    assert page.input.calls[-1] == ("ignore", True, "session-1")

    await status.release_interaction_lock(page)
    assert page.input.calls[-1] == ("ignore", False, "session-1")


async def test_interaction_lock_auto_unlocks_the_login_page() -> None:
    page = _LockPage("https://www.linkedin.com/login?fromSignIn=true")
    lock = await status.ensure_interaction_lock(page)
    assert lock is not None
    assert await lock._on_login_page() is True
    await status.release_interaction_lock(page)


async def test_emit_llm_uses_the_reporter_panel() -> None:
    page = _FakePage()
    emitted: list[str] = []
    reporter = _reporter(page, emitted)

    status.emit_llm(reporter, "answered 'City'", "'Sydney' (location)")
    await _drain()

    assert emitted == ["LLM: answered 'City' - 'Sydney' (location)"]
    _js, args = page.calls[0]
    assert args[0] == "llm"


async def _stop_watcher(lock) -> None:
    """Stop the automatic watch task so a test can drive one tick by hand."""
    if lock._task is not None:
        lock._task.cancel()
        await asyncio.gather(lock._task, return_exceptions=True)
        lock._task = None


async def test_watch_tick_in_flight_cannot_re_lock_a_human_turn() -> None:
    """BUG-083: a tick that probed the page before the human turn began.

    The old tick applied ``ignore=true`` after ``begin_human_turn`` had already
    unlocked the page, leaving the human unable to type for the whole turn.
    """
    page = _SlowInspectPage()
    lock = await status.ensure_interaction_lock(page)
    assert lock is not None
    await _stop_watcher(lock)

    tick = asyncio.create_task(lock._refresh())
    await asyncio.wait_for(page.inspect_started.wait(), 1)

    await status.begin_human_turn(page)
    assert page.input.calls[-1] == ("ignore", False, "session-1")

    page.inspect_release.set()
    await tick

    assert page.input.calls[-1] == ("ignore", False, "session-1")
    await status.release_interaction_lock(page)


async def test_watch_tick_does_not_probe_the_page_during_a_human_turn() -> None:
    page = _SlowInspectPage()
    lock = await status.ensure_interaction_lock(page)
    assert lock is not None
    await _stop_watcher(lock)

    await status.begin_human_turn(page)
    page.inspect_started.clear()
    await lock._refresh()

    assert not page.inspect_started.is_set()
    await status.release_interaction_lock(page)


async def test_automation_command_tail_cannot_re_lock_a_human_turn() -> None:
    """BUG-083: a human turn starting mid-command must win over the command tail."""
    page = _SlowCommandPage()
    lock = await status.ensure_interaction_lock(page)
    assert lock is not None
    await _stop_watcher(lock)

    command = asyncio.create_task(
        page._client.send.Input.dispatchMouseEvent({"x": 1}, session_id="session-1")
    )
    await asyncio.wait_for(page.input.started.wait(), 1)

    await status.begin_human_turn(page)
    page.input.release.set()
    await command

    assert page.input.calls[-1] == ("ignore", False, "session-1")
    await status.release_interaction_lock(page)


async def test_apply_true_during_a_human_turn_keeps_the_page_interactive() -> None:
    page = _LockPage()
    lock = await status.ensure_interaction_lock(page)
    assert lock is not None
    await _stop_watcher(lock)

    await status.begin_human_turn(page)
    await lock._apply(True)  # any late "lock" request while the human owns it

    assert page.input.calls[-1] == ("ignore", False, "session-1")
    await status.release_interaction_lock(page)


async def test_nested_human_turns_stay_unlocked_until_the_last_one_ends() -> None:
    page = _LockPage()
    lock = await status.ensure_interaction_lock(page)
    assert lock is not None
    await _stop_watcher(lock)

    await status.begin_human_turn(page)
    await status.begin_human_turn(page)
    await status.end_human_turn(page)
    assert page.input.calls[-1] == ("ignore", False, "session-1")

    await status.end_human_turn(page)
    assert page.input.calls[-1] == ("ignore", True, "session-1")
    await status.release_interaction_lock(page)
