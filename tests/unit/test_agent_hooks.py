"""Unit tests for the browser-use agent step hooks (Tasks 17; found in CP-B).

These pin the behaviour that keeps a long, watchable run from stalling: after each
agent step, a stale (post-navigation-failure) browser session is re-attached so the
next step has a live page, and the flow is logged one line per step so a human can
watch it.

Pure: a fake agent object stands in for the real browser-use ``Agent``.
"""

from __future__ import annotations

import asyncio

from src.tools import agent_hooks


class _FakeBrowser:
    def __init__(self, *, alive: bool) -> None:
        self._cdp_client_root = object() if alive else None
        self.started = 0

    async def start(self) -> None:
        self.started += 1
        self._cdp_client_root = object()

    async def get_current_page_url(self) -> str:
        return "https://example.test/"


class _FakeState:
    def __init__(self, n_steps: int) -> None:
        self.n_steps = n_steps


class _FakeAgent:
    def __init__(self, browser: _FakeBrowser, n_steps: int = 3) -> None:
        self.browser_session = browser
        self.state = _FakeState(n_steps)


def test_step_logger_prints_one_line_per_step() -> None:
    lines: list[str] = []
    logger = agent_hooks.StepLogger(out=lines.append)

    asyncio.run(logger(_FakeAgent(_FakeBrowser(alive=True))))

    assert len(lines) == 1
    assert "step 3" in lines[0]
    assert "https://example.test/" in lines[0]


def test_step_logger_never_raises_when_the_browser_is_gone() -> None:
    lines: list[str] = []

    class _DeadBrowser:
        async def get_current_page_url(self) -> str:
            raise RuntimeError("Cannot navigate - browser not connected")

    class _Agent:
        browser_session = _DeadBrowser()
        state = _FakeState(1)

    logger = agent_hooks.StepLogger(out=lines.append)

    asyncio.run(logger(_Agent()))  # must not raise

    assert len(lines) == 1
    assert "(unknown)" in lines[0]


def test_stale_session_is_recovered_on_step_end() -> None:
    browser = _FakeBrowser(alive=False)
    on_step_end = agent_hooks.build_on_step_end(recover=True)

    asyncio.run(on_step_end(_FakeAgent(browser)))

    assert browser.started == 1
    assert browser._cdp_client_root is not None


def test_live_session_is_left_alone_on_step_end() -> None:
    browser = _FakeBrowser(alive=True)
    on_step_end = agent_hooks.build_on_step_end(recover=True)

    asyncio.run(on_step_end(_FakeAgent(browser)))

    assert browser.started == 0


def test_recovery_can_be_disabled_and_logging_composes() -> None:
    lines: list[str] = []
    browser = _FakeBrowser(alive=False)
    on_step_end = agent_hooks.build_on_step_end(
        logger=agent_hooks.StepLogger(out=lines.append),
        recover=False,
    )

    asyncio.run(on_step_end(_FakeAgent(browser)))

    assert browser.started == 0  # recover=False
    assert len(lines) == 1  # logging still ran


def test_session_is_alive_false_when_no_cdp_client() -> None:
    class _Stub:
        _cdp_client_root = None

        def is_cdp_connected(self) -> bool:
            return False

    assert asyncio.run(agent_hooks.session_is_alive(_Stub())) is False
    assert asyncio.run(agent_hooks.session_is_alive(_FakeBrowser(alive=True))) is True


def test_recover_session_noop_when_already_alive() -> None:
    browser = _FakeBrowser(alive=True)

    attempted = asyncio.run(agent_hooks.recover_session(browser))

    assert attempted is False
    assert browser.started == 0
