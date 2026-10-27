"""Offline tests for the always-on graph crash guard (Task 11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.configuration import SelfHealingSettings, Settings
from src.nodes import self_heal_guard as guard
from src.state import JobDescription, Task2Outcome
from src.tools.self_healing.models import CapturedFailure, FailureEvidence, FailureRecord
from src.tools.self_healing.recovery import ReopenResult


def _settings(tmp_path: Path, **healing) -> Settings:
    healing.setdefault("max_repair_attempts", 2)
    return Settings(
        self_healing=SelfHealingSettings(**healing),
        data_dir=tmp_path / "data",
    )


def _captured(tmp_path: Path) -> CapturedFailure:
    return CapturedFailure(
        fingerprint="crashfingerprint",
        category="browser_error",
        symptom="unexpected crash while opening the next job",
        bundle_dir=str(tmp_path / "bundle"),
        evidence=FailureEvidence(
            error="boom",
            page_url="https://www.linkedin.com/jobs/search-results/?currentJobId=1",
        ),
    )


def _record(tmp_path: Path) -> FailureRecord:
    return FailureRecord(
        fingerprint="crashfingerprint",
        category="browser_error",
        bug_id="BUG-900",
        bug_path=str(tmp_path / "known Bugs" / "self_healing_bugs.md"),
        bundle_dir=str(tmp_path / "bundle"),
        symptom="unexpected crash",
    )


def _reopened() -> ReopenResult:
    return ReopenResult(
        run_id="run-2",
        task2=Task2Outcome(job_title="Backend Engineer"),
        description=JobDescription(title="Backend Engineer"),
    )


async def test_crash_guard_records_and_retries_the_same_node(tmp_path: Path) -> None:
    calls: list[str] = []
    node_states: list[dict] = []

    async def node_fn(state):
        node_states.append(dict(state))
        calls.append(state.get("browser_run_id", ""))
        return {"status": "applied", "log": ["next_job: opened QA Engineer"]}

    result = await guard.heal_node_failure(
        "next_job",
        {"dry_run": False, "browser_run_id": "run-1", "search_query": "python"},
        "boom",
        "Traceback: boom",
        node_fn=node_fn,
        reopen="results",
        settings=_settings(tmp_path),
        progress=lambda _message: None,
        bug_root=tmp_path,
        capture_fn=lambda *a, **k: _value(_captured(tmp_path)),
        record_fn=lambda captured: _record(tmp_path),
        close_fn=lambda run_id, settings: _value((True, "closed")),
        repair_fn=lambda settings, captured, record, notify: _value((True, "tests passed")),
        reopen_results_fn=lambda target, settings, notify, captured: _value(_reopened()),
    )

    assert result["status"] == "applied"
    assert result["browser_run_id"] == "run-2"
    assert result["self_healing"].recovered is True
    assert result["self_healing"].bug_ids == ["BUG-900"]
    # The node was retried exactly once, with the recovered run id, not run-1.
    assert calls == ["run-2"]
    assert node_states[0]["browser_run_id"] == "run-2"
    assert node_states[0]["task2"].job_title == "Backend Engineer"
    assert any("recovered and resumed next_job" in line for line in result["log"])


async def test_crash_guard_stops_after_the_attempt_cap(tmp_path: Path) -> None:
    attempts: list[str] = []

    async def node_fn(state):
        attempts.append(state.get("browser_run_id", ""))
        raise RuntimeError("still broken")

    result = await guard.heal_node_failure(
        "match",
        {"dry_run": False, "browser_run_id": "run-1"},
        "boom",
        "Traceback: boom",
        node_fn=node_fn,
        reopen="job",
        settings=_settings(tmp_path, max_repair_attempts=2),
        progress=lambda _message: None,
        bug_root=tmp_path,
        capture_fn=lambda *a, **k: _value(_captured(tmp_path)),
        record_fn=lambda captured: _record(tmp_path),
        close_fn=lambda run_id, settings: _value((True, "closed")),
        repair_fn=lambda settings, captured, record, notify: _value((True, "tests passed")),
        reopen_fn=lambda target, settings, notify: _value(_reopened()),
    )

    assert result["status"] == "failed"
    outcome = result["self_healing"]
    assert outcome.recovered is False
    assert outcome.exhausted is True
    assert outcome.attempts == 2
    assert len(attempts) == 2
    assert result["errors"]


async def test_reopen_none_closes_the_self_launched_browser_before_retrying(
    tmp_path: Path,
) -> None:
    """BUG-065: a self-launching node's loop closes its browser before retrying."""
    closed: list = []
    calls: list[str] = []

    async def node_fn(state):
        calls.append("node")
        return {"status": "applied", "log": ["browse: recovered"]}

    async def close_fn(run_id, settings):
        closed.append(run_id)
        return True, "closed the self-launched browser"

    result = await guard.heal_node_failure(
        "browse",
        {"dry_run": False},
        "browse: job search returned no results",
        "",
        node_fn=node_fn,
        reopen=None,
        settings=_settings(tmp_path),
        progress=lambda _message: None,
        bug_root=tmp_path,
        capture_fn=lambda *a, **k: _value(_captured(tmp_path)),
        record_fn=lambda captured: _record(tmp_path),
        close_fn=close_fn,
        repair_fn=lambda settings, captured, record, notify: _value((True, "skipped")),
    )

    # No run id: the injected self-launching close is used, not the no-op default.
    assert closed == [None]
    assert result["status"] == "applied"
    assert result["self_healing"].recovered is True
    assert calls == ["node"]


async def test_guard_node_runs_the_heal_loop_for_an_uncaught_crash(monkeypatch) -> None:
    seen: dict = {}

    async def boom(state):
        raise RuntimeError("kaboom")

    async def fake_heal(stage, state, error, traceback_text, **kwargs):
        seen["stage"] = stage
        seen["error"] = error
        seen["reopen"] = kwargs.get("reopen")
        return {"status": "recovered", "self_healing": None}

    monkeypatch.setattr(guard, "heal_node_failure", fake_heal)
    wrapped = guard.guard_node("next_job", boom, reopen="results")

    result = await wrapped({"dry_run": False, "browser_run_id": "run-1"})

    assert result["status"] == "recovered"
    assert seen == {"stage": "next_job", "error": "kaboom", "reopen": "results"}


async def test_next_job_lets_a_crash_propagate_to_the_guard(monkeypatch) -> None:
    import src.nodes.apply_loop as apply_loop
    import src.tools.linkedin_apply_loop as loop

    async def fake_open(*args, **kwargs):
        raise RuntimeError("next job crashed")

    monkeypatch.setattr(loop, "open_next_job", fake_open)
    monkeypatch.setattr(apply_loop, "load_settings", lambda: _settings(Path(".")))

    with pytest.raises(RuntimeError, match="next job crashed"):
        await apply_loop.next_job(
            {
                "dry_run": False,
                "browser_run_id": "run-1",
                "task2": Task2Outcome(job_title="Backend Engineer"),
            }
        )


async def _value(value):
    return value
