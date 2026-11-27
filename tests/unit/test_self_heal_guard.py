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

    # ``guard_node`` resolves ``heal_node_failure`` in its own module.
    from src.nodes.self_heal_guard import guard as guard_module

    monkeypatch.setattr(guard_module, "heal_node_failure", fake_heal)
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


# --- Task 33: an unrecovered node crash writes one linked crash bundle ---------


@pytest.fixture
def crash_dir(tmp_path, monkeypatch) -> Path:
    from src.tools.crash_logs.config import load_crash_config
    from src.tools.crash_logs.runtime import reset_run_context

    monkeypatch.setenv("AUTOJOB_CRASH_LOG_ENABLED", "true")
    reset_run_context().config = load_crash_config(tmp_path / "crash-data")
    return tmp_path / "crash-data" / "crash_logs"


def _crash_records(crash_dir: Path) -> list[dict]:
    import json

    if not crash_dir.exists():
        return []
    return [
        json.loads((path / "crash.json").read_text(encoding="utf-8"))
        for path in sorted(crash_dir.iterdir()) if path.is_dir()
    ]


def _boom() -> RuntimeError:
    try:
        raise RuntimeError("kaboom")
    except RuntimeError as exc:
        return exc


@pytest.mark.parametrize("healing", [{"enabled": False}, {"max_repair_attempts": 0}])
async def test_disabled_self_healing_writes_a_node_crash_bundle(tmp_path, crash_dir, healing):
    async def node_fn(state):
        raise AssertionError("must not retry")

    exc = _boom()
    result = await guard.heal_node_failure(
        "fill", {"dry_run": False, "log": ["fill: step 1"]}, "kaboom", "Traceback: kaboom",
        node_fn=node_fn, settings=_settings(tmp_path, **healing),
        progress=lambda _message: None, bug_root=tmp_path, exc=exc,
    )

    assert result["status"] == "failed"
    [record] = _crash_records(crash_dir)
    assert record["kind"] == "node_crash" and record["stage"] == "fill"
    assert record["exception"]["type"] == "RuntimeError"
    assert record["context"]["stop_reason"] == "self-healing is disabled"
    assert "fill: step 1" in record["log"]


async def test_capture_failure_writes_a_bundle_with_the_capture_error(tmp_path, crash_dir):
    async def node_fn(state):
        raise AssertionError("must not retry")

    async def broken_capture(*args, **kwargs):
        raise OSError("screenshot pipe closed")

    result = await guard.heal_node_failure(
        "match", {"dry_run": False}, "kaboom", "Traceback: kaboom",
        node_fn=node_fn, settings=_settings(tmp_path),
        progress=lambda _message: None, bug_root=tmp_path,
        capture_fn=broken_capture, exc=_boom(),
    )

    assert result["status"] == "failed"
    [record] = _crash_records(crash_dir)
    assert record["context"]["capture_error"] == "OSError: screenshot pipe closed"
    assert "kaboom" in record["exception"]["traceback"]


async def test_exhausted_loop_writes_one_linked_bundle(tmp_path, crash_dir):
    async def node_fn(state):
        raise RuntimeError("still broken")

    await guard.heal_node_failure(
        "match", {"dry_run": False, "browser_run_id": "run-1"}, "kaboom", "Traceback",
        node_fn=node_fn, reopen="job", settings=_settings(tmp_path, max_repair_attempts=2),
        progress=lambda _message: None, bug_root=tmp_path,
        capture_fn=lambda *a, **k: _value(_captured(tmp_path)),
        record_fn=lambda captured: _record(tmp_path),
        close_fn=lambda run_id, settings: _value((True, "closed")),
        repair_fn=lambda settings, captured, record, notify: _value((True, "tests passed")),
        reopen_fn=lambda target, settings, notify: _value(_reopened()),
        exc=_boom(),
    )

    [record] = _crash_records(crash_dir)
    assert record["self_healing"]["bug_id"] == "BUG-900"
    assert record["self_healing"]["bundle"] == str(tmp_path / "bundle")
    assert record["self_healing"]["attempts"] == 2
    assert record["self_healing"]["recovered"] is False
    assert record["context"]["last_error"] == "still broken"
    # The self-healing bundle owns the page evidence; nothing is duplicated.
    assert record["browser"]["error"] == "page capture skipped"


async def test_recovered_crash_writes_no_crash_bundle(tmp_path, crash_dir):
    async def node_fn(state):
        return {"status": "applied"}

    result = await guard.heal_node_failure(
        "next_job", {"dry_run": False, "browser_run_id": "run-1"}, "boom", "Traceback",
        node_fn=node_fn, reopen="results", settings=_settings(tmp_path),
        progress=lambda _message: None, bug_root=tmp_path,
        capture_fn=lambda *a, **k: _value(_captured(tmp_path)),
        record_fn=lambda captured: _record(tmp_path),
        close_fn=lambda run_id, settings: _value((True, "closed")),
        repair_fn=lambda settings, captured, record, notify: _value((True, "tests passed")),
        reopen_results_fn=lambda target, settings, notify, captured: _value(_reopened()),
        exc=_boom(),
    )

    assert result["self_healing"].recovered is True
    assert _crash_records(crash_dir) == []
