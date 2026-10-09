"""Unit tests for Task 4's browser-use LLM agent fill (no real browser/LLM)."""

from __future__ import annotations

import asyncio

from src.configuration import LlmSettings, SessionSettings, Settings
from src.tools import agent_fill


class _Page:
    """Records the JS the agent fill installs/removes, guarding the page."""

    def __init__(self) -> None:
        self.js: list[str] = []
        self.guard_active = False

    async def evaluate(self, js: str, *args):
        self.js.append(js)
        if js == agent_fill.GUARD_NAV_JS:
            self.guard_active = True
        elif js == agent_fill.UNGUARD_NAV_JS:
            self.guard_active = False
        return True


class _Agent:
    def __init__(
        self,
        *,
        delay: float = 0.0,
        error: Exception | None = None,
        steps: int = 3,
        success: bool | None = True,
    ):
        self.delay = delay
        self.error = error
        self.steps = steps
        self.success = success
        self.max_steps: int | None = None

    async def run(self, max_steps: int = 500):
        self.max_steps = max_steps
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        history = type("History", (), {"history": [object()] * self.steps})()
        history.is_successful = lambda: self.success
        return history


class _FocusSession:
    """Records the agent-focus requests the runner makes."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.focused: list[tuple] = []
        self.error = error

    async def get_or_create_cdp_session(self, target_id=None, focus=True):
        self.focused.append((target_id, focus))
        if self.error is not None:
            raise self.error
        return object()


def _settings(**llm) -> Settings:
    llm.setdefault("model", "deepseek/deepseek-v4.1-flash")
    return Settings(session=SessionSettings(agent_fill=True), llm=LlmSettings(**llm))


def test_build_agent_task_lists_answers_and_pins_rules() -> None:
    task = agent_fill.build_agent_task({"city": "Sydney"}, title="Contact info")

    assert "Contact info" in task
    assert '"city": "Sydney"' in task
    assert "never guess" in task
    assert "Do NOT click Next" in task
    assert "Do NOT upload" in task


def test_build_agent_llm_returns_none_without_a_model() -> None:
    assert agent_fill.build_agent_llm(Settings()) is None


async def test_agent_fill_is_disabled_without_an_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    page = _Page()
    report = await agent_fill.fill_known_fields_with_agent(
        page, object(), {"city": "Sydney"}, _settings(), lambda _m: None
    )

    assert report is None
    assert page.js == []


async def test_agent_fill_runs_and_removes_the_guard(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    page = _Page()
    agent = _Agent(steps=2)
    notes: list[str] = []

    report = await agent_fill.fill_known_fields_with_agent(
        page,
        object(),
        {"city": "Sydney"},
        _settings(max_steps=7),
        notes.append,
        agent_factory=lambda session, llm, task, settings: agent,
        llm=object(),
    )

    assert report is not None and report.ran is True
    assert report.note == "agent finished"
    assert report.steps == 2
    assert agent.max_steps == 7
    assert page.js[0] == agent_fill.GUARD_NAV_JS
    assert page.js[-1] == agent_fill.UNGUARD_NAV_JS
    assert page.guard_active is False
    assert any("agent finished" in note for note in notes)


async def test_agent_fill_focuses_the_open_form_tab(monkeypatch) -> None:
    """The agent must be pointed at the actor page's target, not about:blank."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    page = _Page()
    page._target_id = "TARGET-123"  # type: ignore[attr-defined]
    session = _FocusSession()

    report = await agent_fill.fill_known_fields_with_agent(
        page,
        session,
        {"city": "Sydney"},
        _settings(),
        lambda _m: None,
        agent_factory=lambda session, llm, task, settings: _Agent(),
        llm=object(),
    )

    assert report is not None and report.ran is True
    assert session.focused == [("TARGET-123", True)]


async def test_agent_fill_tolerates_focus_failure(monkeypatch) -> None:
    """A failed focus attempt is swallowed; the run still proceeds."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    page = _Page()
    page._target_id = "TARGET-123"  # type: ignore[attr-defined]
    session = _FocusSession(error=RuntimeError("no cdp"))

    report = await agent_fill.fill_known_fields_with_agent(
        page,
        session,
        {"city": "Sydney"},
        _settings(),
        lambda _m: None,
        agent_factory=lambda session, llm, task, settings: _Agent(),
        llm=object(),
    )

    assert report is not None and report.ran is True
    assert report.note == "agent finished"


async def test_agent_fill_reports_an_unsuccessful_result(monkeypatch) -> None:
    """A final ``success=False`` is surfaced in the report note."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    page = _Page()

    report = await agent_fill.fill_known_fields_with_agent(
        page,
        object(),
        {"city": "Sydney"},
        _settings(),
        lambda _m: None,
        agent_factory=lambda session, llm, task, settings: _Agent(success=False),
        llm=object(),
    )

    assert report is not None
    assert report.note == "agent finished without confirming success"


async def test_agent_fill_times_out_and_still_removes_the_guard(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    page = _Page()

    report = await agent_fill.fill_known_fields_with_agent(
        page,
        object(),
        {"city": "Sydney"},
        _settings(timeout_seconds=0.01),
        lambda _m: None,
        agent_factory=lambda session, llm, task, settings: _Agent(delay=1.0),
        llm=object(),
    )

    assert report is not None and report.ran is True
    assert "timed out" in report.note
    assert page.guard_active is False


async def test_agent_fill_swallows_failures(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    page = _Page()

    report = await agent_fill.fill_known_fields_with_agent(
        page,
        object(),
        {"city": "Sydney"},
        _settings(),
        lambda _m: None,
        agent_factory=lambda session, llm, task, settings: _Agent(error=RuntimeError("boom")),
        llm=object(),
    )

    assert report is not None
    assert "agent failed: RuntimeError: boom" in report.note
    assert page.guard_active is False


async def test_agent_fill_skips_when_nothing_is_known(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    page = _Page()
    called = False

    def factory(*args, **kwargs):
        nonlocal called
        called = True
        return _Agent()

    report = await agent_fill.fill_known_fields_with_agent(
        page,
        object(),
        {},
        _settings(),
        lambda _m: None,
        agent_factory=factory,
        llm=object(),
    )

    assert report is not None and report.ran is False
    assert called is False
    assert page.js == []
