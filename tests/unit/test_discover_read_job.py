"""Unit tests for `discover.read_job`'s page-safety seam (Task 17; found in CP-B).

The 2026-09-30 real-browser CP-B run of job ``4468706364`` crashed in discovery
*after* the browser-use agent had successfully read the job:

    ValueError: Expected at least one handler to return a non-None result, but none did!
    BrowserStateRequestEvent ... -> {}

In browser-use 0.13.10 the ``BrowserStateRequestEvent`` handler lives for the
duration of an ``Agent`` run; once ``agent.run()`` returns it is gone, so
``Browser.get_state_as_text()`` cannot be called from the graph nodes. The guard's
page read must therefore use a primitive that survives outside an agent run (the
CDP-level ``Page.evaluate``) — and it must still halt on a rate-limit page.

These tests stub the agent at ``discover.run_task`` and emulate the real browser's
post-run behaviour: ``get_state_as_text`` is dead, the CDP page read is alive.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.configuration import GuardSettings, Paths
from src.nodes import discover
from src.tools import linkedin, store
from src.tools.browser_agent import AgentRunResult
from src.tools.guard import Guard, GuardHalt

JOB_URL = "https://www.linkedin.com/jobs/view/4000000001/"


def _paths(root: Path) -> Paths:
    data = root / "data"
    return Paths(
        root=root,
        config=root / "config",
        resumes=root / "resumes",
        data=data,
        db=data / "autojobapply.db",
        profile=data / "profile",
        artifacts=data / "artifacts",
        stop=data / "STOP",
    )


def _guard(paths: Paths) -> Guard:
    conn = store.connect(":memory:")
    store.init_db(conn)
    return Guard(GuardSettings(), paths, conn, sleep=lambda _seconds: None)


class _FakePage:
    """A browser-use ``Page`` actor: its CDP read works even after an agent run."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def evaluate(self, page_function: str, *args: Any) -> str:
        return self._text


class _FakeBrowser:
    """Emulates browser-use 0.13.10 *after* ``Agent.run()`` returned.

    ``get_state_as_text`` raises exactly what the real browser raised in CP-B; the
    CDP-level page read is the only working way to see the page.
    """

    def __init__(self, page_text: str) -> None:
        self._page_text = page_text

    async def get_state_as_text(self) -> str:
        raise ValueError(
            "Expected at least one handler to return a non-None result, but none did!"
        )

    async def get_current_page(self) -> _FakePage:
        return _FakePage(self._page_text)


def _stub_run_task(monkeypatch: pytest.MonkeyPatch, *, easy_apply: bool = True) -> None:
    extraction = linkedin.JobExtraction(
        title="Full Stack Engineer",
        company="Example Co",
        description="Build things.",
        easy_apply=easy_apply,
    )

    async def fake_run_task(task: str, **kwargs: Any) -> AgentRunResult:
        return AgentRunResult(done=True, successful=True, structured_output=extraction)

    monkeypatch.setattr(discover, "run_task", fake_run_task)


def test_read_job_survives_a_dead_state_as_text_after_an_agent_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The guard's page read must not depend on the agent's event handlers.

    RED before the fix: ``read_job`` called ``browser.get_state_as_text()`` and the
    run died with the CP-B ``ValueError`` although the job had been read fine.
    """
    _stub_run_task(monkeypatch)
    guard = _guard(_paths(tmp_path))
    browser = _FakeBrowser("Full Stack Engineer at Example Co. Easy Apply.")

    job = asyncio.run(discover.read_job(browser, object(), JOB_URL, guard=guard))

    assert job["job_id"] == "4000000001"
    assert job["easy_apply"] is True


def test_read_job_halts_on_a_rate_limit_page(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The working page read stays wired to the guard: a checkpoint page halts."""
    _stub_run_task(monkeypatch)
    paths = _paths(tmp_path)
    guard = _guard(paths)
    browser = _FakeBrowser("You've reached the weekly invitation limit. Checkpoint required.")

    with pytest.raises(GuardHalt, match="rate-limit"):
        asyncio.run(discover.read_job(browser, object(), JOB_URL, guard=guard))

    assert paths.stop.exists()
