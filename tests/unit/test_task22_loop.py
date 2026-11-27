"""Selected submission mode, loop counting, and crash behavior."""

import pytest

from src.configuration import SessionSettings, Settings
from src.graph import _route_after_submit
from src.nodes import apply_loop
from src.nodes.submission_guard import guard_submission
from src.nodes.verify import _task4_succeeded
from src.state import Task2Outcome, Task4Outcome
from src.tools import linkedin_auto_submit as submit


@pytest.mark.asyncio
@pytest.mark.parametrize("observed", ["submitted", "unconfirmed", "blocked"])
async def test_auto_mode_counts_only_confirmation_and_obeys_cap(monkeypatch, observed):
    form = Task4Outcome(form_open=True, reached_terminal_step=True, resume_attached=True)
    async def automatic(run_id, outcome, settings, **kwargs):
        outcome.submission_attempted = True
        outcome.submitted = observed == "submitted"
        return submit.AutoSubmitResult(observed, "review required")
    monkeypatch.setattr(submit, "submit_application", automatic)
    monkeypatch.setattr(apply_loop, "load_settings", lambda: Settings(
        session=SessionSettings(max_jobs_per_run=1)))
    state = {"dry_run": False, "submission_mode": "auto", "browser_run_id": "run",
             "task2": Task2Outcome(job_title="Engineer"), "task4": form}
    update = await apply_loop.await_submit(state)
    assert update["task8"].jobs_applied == int(observed == "submitted")
    assert update["task8"].stopped_reason
    assert _route_after_submit({**state, **update}) == "cleanup"
    assert _task4_succeeded({**state, **update})
    if observed == "submitted":
        assert not _task4_succeeded({**state, **update, "submission_mode": "manual"})


@pytest.mark.asyncio
async def test_automatic_submission_continues_until_cap(monkeypatch):
    async def automatic(*args, **kwargs):
        return submit.AutoSubmitResult("submitted")
    monkeypatch.setattr(submit, "submit_application", automatic)
    monkeypatch.setattr(apply_loop, "load_settings", lambda: Settings(
        session=SessionSettings(max_jobs_per_run=2)))
    state = {"dry_run": False, "submission_mode": "auto", "browser_run_id": "run",
             "task4": Task4Outcome(reached_terminal_step=True)}
    first = await apply_loop.await_submit(state)
    assert _route_after_submit({**state, **first}) == "next_job"
    second = await apply_loop.await_submit({**state, **first})
    assert second["task8"].jobs_applied == 2
    assert _route_after_submit({**state, **second}) == "cleanup"


@pytest.mark.asyncio
async def test_automatic_crash_never_enters_recovery(monkeypatch):
    from src.nodes.self_heal_guard import guard as self_heal_guard

    async def crash(_):
        raise RuntimeError("connection lost after Submit")
    async def unexpected(*args, **kwargs):
        pytest.fail("automatic submission must not reopen and retry")
    monkeypatch.setattr(self_heal_guard, "heal_node_failure", unexpected)
    state = {"dry_run": False, "submission_mode": "auto"}
    update = await guard_submission(crash)(state)
    assert "review" in update["task8"].stopped_reason
    assert _route_after_submit(update) == "cleanup"


@pytest.mark.asyncio
async def test_automatic_crash_writes_a_submission_interrupted_bundle(tmp_path, monkeypatch):
    """Task 33: evidence is recorded, the update is unchanged, nothing is retried."""
    import json

    from src.tools.crash_logs.config import load_crash_config
    from src.tools.crash_logs.runtime import reset_run_context

    monkeypatch.setenv("AUTOJOB_CRASH_LOG_ENABLED", "true")
    reset_run_context().config = load_crash_config(tmp_path)
    calls = []

    async def crash(_):
        calls.append("submit")
        raise RuntimeError("connection lost after Submit")

    update = await guard_submission(crash)({"dry_run": False, "submission_mode": "auto"})

    assert calls == ["submit"]
    assert update["status"] == "needs_review"
    assert update["task8"].last_submission_status == "interrupted"
    [bundle] = [path for path in (tmp_path / "crash_logs").iterdir() if path.is_dir()]
    record = json.loads((bundle / "crash.json").read_text(encoding="utf-8"))
    assert record["kind"] == "submission_interrupted" and record["stage"] == "await_submit"
    assert "connection lost after Submit" in record["exception"]["traceback"]
