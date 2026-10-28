"""Offline tests for Task 1-10 task-level self-healing."""

from __future__ import annotations

import pytest

from src.configuration import SessionSettings, Settings
from src.nodes import task_self_heal as task_heal
from src.state import (
    JobDescription,
    Task1Outcome,
    Task2Outcome,
    Task3Outcome,
    Task8Outcome,
)
from src.tools.self_healing.buglog import _scope_for, record_failure
from src.tools.self_healing.fingerprint import (
    classify_failure,
    is_recoverable,
    symptom_for,
)
from src.tools.self_healing.models import (
    CapturedFailure,
    FailureEvidence,
    SelfHealingOutcome,
)


def _browse_failure(*, logged_in: bool = True, results: bool = True) -> dict:
    return {
        "status": "failed",
        "task1": Task1Outcome(
            logged_in=logged_in,
            results_found=results,
            easy_apply_filter_selected=results,
        ),
        "task2": Task2Outcome(),
        "job_description": JobDescription(),
        "errors": ["browse: test failure"],
    }


def _browse_success() -> dict:
    return {
        "status": "applied",
        "task1": Task1Outcome(
            logged_in=True,
            results_found=True,
            easy_apply_filter_selected=True,
            date_posted_filter_selected=True,
            date_posted_filter_value="past_24_hours",
        ),
        "task2": Task2Outcome(easy_apply_clicked=True, application_form_opened=True),
        "job_description": JobDescription(title="Backend Engineer", body="Python"),
        "log": ["browse: recovered"],
    }


def test_task_failure_reason_reads_browse_outcomes() -> None:
    assert task_heal.task_failure_reason("browse", _browse_failure(results=False)) == (
        "browse: job search returned no results"
    )
    assert task_heal.task_failure_reason("browse", _browse_success()) == ""


def test_task_failure_reason_requires_date_posted_filter() -> None:
    update = _browse_success()
    update["task1"].date_posted_filter_selected = False
    reason = task_heal.task_failure_reason("browse", update)
    assert "Date posted filter" in reason
    assert task_heal.task_failure_is_recoverable("browse", reason, update) is True


def test_task_failure_reason_reads_match_outcomes() -> None:
    assert task_heal.task_failure_reason(
        "match", {"task3": Task3Outcome(error="match: LLM timed out")}
    ) == "match: LLM timed out"
    assert task_heal.task_failure_reason(
        "match", {"task3": Task3Outcome(selected_path="resumes/a.pdf")}
    ) == ""
    # Task 16: a deliberate strict-mode skip is not a task failure.
    assert task_heal.task_failure_reason(
        "match",
        {
            "status": "skipped",
            "task3": Task3Outcome(no_match=True, fit="partial"),
            "task16": None,
        },
    ) == ""


def test_task_failure_reason_ignores_exception_only_stages() -> None:
    assert task_heal.task_failure_reason("await_submit", {"errors": ["boom"]}) == ""
    assert task_heal.task_failure_reason("fill", {"errors": ["boom"]}) == ""


def test_task_failure_reason_reads_next_job_pagination_stops() -> None:
    failed = Task8Outcome(
        stopped_reason=(
            "results pagination could not advance: pagination controls not found"
        )
    )
    assert "pagination" in task_heal.task_failure_reason("next_job", {"task8": failed})
    clean_last_page = Task8Outcome(stopped_reason="no next results page")
    assert task_heal.task_failure_reason("next_job", {"task8": clean_last_page}) == ""
    exhausted = Task8Outcome(
        stopped_reason="skipped 22 applied job(s); every job on every results page is Applied"
    )
    assert task_heal.task_failure_reason("next_job", {"task8": exhausted}) == ""


@pytest.mark.asyncio
async def test_browse_login_gate_is_not_retried(monkeypatch) -> None:
    called = {"heal": False}

    async def node_fn(state):
        return _browse_failure(logged_in=False)

    async def fake_heal(*args, **kwargs):
        called["heal"] = True
        raise AssertionError("the human login gate must not be retried")

    monkeypatch.setattr(task_heal, "heal_node_failure", fake_heal)
    guarded = task_heal.guard_task_node("browse", node_fn, reopen=None)

    result = await guarded({"dry_run": False})

    assert called["heal"] is False
    assert result["task1"].logged_in is False


@pytest.mark.asyncio
async def test_browse_returned_failure_is_retried(monkeypatch) -> None:
    calls: list[str] = []

    async def node_fn(state):
        calls.append("node")
        return _browse_success() if len(calls) > 1 else _browse_failure(results=False)

    async def fake_heal(stage, state, error, traceback_text, *, node_fn, reopen, close_fn=None):
        assert stage == "browse"
        assert error == "browse: job search returned no results"
        assert close_fn is task_heal.close_self_launched_browser
        result = await node_fn(state)
        result["self_healing"] = SelfHealingOutcome(
            enabled=True, recovered=True, attempts=1
        )
        return result

    monkeypatch.setattr(task_heal, "heal_node_failure", fake_heal)
    guarded = task_heal.guard_task_node("browse", node_fn, reopen=None)

    result = await guarded({"dry_run": False})

    assert calls == ["node", "node"]
    assert result["status"] == "applied"
    assert result["self_healing"].recovered is True


@pytest.mark.asyncio
async def test_match_transient_error_is_retried(monkeypatch) -> None:
    calls: list[str] = []

    async def node_fn(state):
        calls.append("node")
        if len(calls) == 1:
            return {"status": "failed", "task3": Task3Outcome(error="match: LLM timeout")}
        return {"status": "matched", "task3": Task3Outcome(selected_path="resumes/a.pdf")}

    async def fake_heal(stage, state, error, traceback_text, *, node_fn, reopen, close_fn=None):
        assert stage == "match"
        assert close_fn is None  # a job node keeps the loop's scoped close
        result = await node_fn(state)
        result["self_healing"] = SelfHealingOutcome(recovered=True, attempts=1)
        return result

    monkeypatch.setattr(task_heal, "heal_node_failure", fake_heal)
    guarded = task_heal.guard_task_node("match", node_fn, reopen="job")

    result = await guarded({"dry_run": False})

    assert calls == ["node", "node"]
    assert result["task3"].selected_path == "resumes/a.pdf"


@pytest.mark.asyncio
async def test_next_job_pagination_failure_is_retried(monkeypatch) -> None:
    calls: list[str] = []

    async def node_fn(state):
        calls.append("node")
        if len(calls) == 1:
            return {
                "status": "stopped",
                "task8": Task8Outcome(
                    stopped_reason=(
                        "results pagination could not advance: "
                        "pagination controls not found"
                    )
                ),
            }
        return {"status": "applied", "task2": Task2Outcome(job_title="Next job")}

    async def fake_heal(stage, state, error, traceback_text, *, node_fn, reopen, **kwargs):
        assert stage == "next_job"
        assert reopen == "results"
        result = await node_fn(state)
        result["self_healing"] = SelfHealingOutcome(recovered=True, attempts=1)
        return result

    monkeypatch.setattr(task_heal, "heal_node_failure", fake_heal)
    guarded = task_heal.guard_task_node("next_job", node_fn, reopen="results")

    result = await guarded({"dry_run": False})

    assert calls == ["node", "node"]
    assert result["status"] == "applied"
    assert result["task2"].job_title == "Next job"


@pytest.mark.asyncio
async def test_match_without_a_resume_is_not_retried(monkeypatch) -> None:
    async def node_fn(state):
        return {"status": "failed", "task3": Task3Outcome(resumes_found=0)}

    async def fake_heal(*args, **kwargs):
        raise AssertionError("an empty/unmatched resume pool must stop gracefully")

    monkeypatch.setattr(task_heal, "heal_node_failure", fake_heal)
    guarded = task_heal.guard_task_node("match", node_fn, reopen="job")

    result = await guarded({"dry_run": False})

    assert not result["task3"].selected_path


@pytest.mark.asyncio
async def test_exhausted_task_heal_keeps_the_task_outcomes(monkeypatch) -> None:
    failure = _browse_failure()

    async def node_fn(state):
        return failure

    async def fake_heal(*args, **kwargs):
        return {
            "status": "failed",
            "errors": ["self-heal(browse): exhausted"],
            "self_healing": SelfHealingOutcome(recovered=False, exhausted=True),
        }

    monkeypatch.setattr(task_heal, "heal_node_failure", fake_heal)
    guarded = task_heal.guard_task_node("browse", node_fn, reopen=None)

    result = await guarded({"dry_run": False})

    assert result["task1"] is failure["task1"]
    assert result["task2"] is failure["task2"]
    assert result["errors"] == ["browse: test failure"]
    assert result["self_healing"].exhausted is True


def _settings(tmp_path, **session) -> Settings:
    return Settings(
        session=SessionSettings(**session) if session else SessionSettings(),
        data_dir=tmp_path / "data",
    )


@pytest.mark.asyncio
async def test_browse_self_heal_closes_the_self_launched_browser(
    monkeypatch, tmp_path
) -> None:
    """BUG-065: a failed browse left its browser open, blocking the retry."""
    seen: dict = {}

    async def node_fn(state):
        return _browse_failure(results=False)

    async def fake_heal(stage, state, error, traceback_text, **kwargs):
        seen["close_fn"] = kwargs.get("close_fn")
        return {"status": "applied", "self_healing": SelfHealingOutcome(recovered=True)}

    monkeypatch.setattr(task_heal, "heal_node_failure", fake_heal)
    guarded = task_heal.guard_task_node("browse", node_fn, reopen=None)

    await guarded({"dry_run": False})

    # The loop is handed the profile-closing close, not the no-op default.
    assert seen["close_fn"] is task_heal.close_self_launched_browser

    # With no registered run it force-closes the dedicated profile browser.
    import src.tools.browser as browser_tools

    killed: list[Settings] = []

    def fake_clean_profile(settings):
        killed.append(settings)
        return 2

    monkeypatch.setattr(browser_tools, "clean_profile", fake_clean_profile)

    closed, detail = await task_heal.close_self_launched_browser(None, _settings(tmp_path))

    assert closed is True
    assert len(killed) == 1
    assert "2" in detail


@pytest.mark.asyncio
async def test_close_self_launched_browser_delegates_a_registered_run(
    monkeypatch, tmp_path
) -> None:
    """A registered run is closed through the scoped path, never profile-wide."""
    calls: list[str] = []

    async def fake_close(run_id, settings):
        calls.append(run_id)
        return True, "closed the run"

    import src.tools.browser as browser_tools

    def fail_clean_profile(settings):  # pragma: no cover - must not be called
        raise AssertionError("a registered run must not trigger a profile-wide kill")

    monkeypatch.setattr(task_heal, "close_run_force", fake_close)
    monkeypatch.setattr(browser_tools, "clean_profile", fail_clean_profile)

    closed, detail = await task_heal.close_self_launched_browser("run-1", _settings(tmp_path))

    assert closed is True
    assert calls == ["run-1"]
    assert detail == "closed the run"


@pytest.mark.asyncio
async def test_close_self_launched_browser_keeps_the_window_when_locks_are_tolerated(
    monkeypatch, tmp_path
) -> None:
    """When stale-lock cleanup is off the retry can launch, so leave it open."""
    import src.tools.browser as browser_tools

    def fail_clean_profile(settings):  # pragma: no cover - must not be called
        raise AssertionError("no profile-wide kill when locks are tolerated")

    monkeypatch.setattr(browser_tools, "clean_profile", fail_clean_profile)

    closed, _detail = await task_heal.close_self_launched_browser(
        None, _settings(tmp_path, clean_stale_profile=False)
    )

    assert closed is True


def test_browse_failures_are_classified_as_search_stops() -> None:
    """BUG-065: a browse stop is not a form-fill 'unknown_exception'."""
    assert classify_failure(
        "browse: job search returned no results", stage="browse"
    ) == "search_no_results"
    assert classify_failure("browse: login not completed", stage="browse") == (
        "login_not_completed"
    )
    assert classify_failure(
        "browse: Easy Apply filter not selected", stage="browse"
    ) == "search_filter_not_selected"
    assert classify_failure(
        "browse: no job Easy Apply button was clicked", stage="browse"
    ) == "easy_apply_job_missing"

    # The bug-log symptom names the real stop, without the form-fill wording.
    assert symptom_for(
        "search_no_results", None, "browse: job search returned no results"
    ) == "the job search returned no results"

    # A search stop is worth retrying; a missed login gate is not.
    assert is_recoverable("search_no_results") is True
    assert is_recoverable("login_not_completed") is False


def test_next_job_pagination_stop_is_not_a_form_fill_exception() -> None:
    """BUG-068: a next_job pagination stop has its own category and scope."""
    error = "next_job: results pagination could not advance: no change after next"
    assert classify_failure(error, stage="next_job") == "pagination_failed"
    assert classify_failure(error) != "pagination_failed"  # fill keeps its rules
    assert symptom_for("pagination_failed", None, error).startswith(
        "the results pagination could not advance"
    )
    assert is_recoverable("pagination_failed") is True
    assert _scope_for("next_job") == "Self-Healing — next job/pagination"


def test_fill_classification_is_unchanged_by_the_stage_argument() -> None:
    """The fill path keeps its existing categories (stage defaults to 'fill')."""
    assert classify_failure("", None, "fill raised: boom") == "unknown_exception"
    assert classify_failure("boom") == "unknown_exception"
    assert classify_failure("") == "unknown"


def test_repair_reloads_the_self_healing_classifier() -> None:
    """A repair may change fingerprint/capture/buglog; retry must load them."""
    from src.tools.self_healing.recovery import _RUNTIME_MODULES

    assert "src.tools.self_healing.fingerprint" in _RUNTIME_MODULES
    assert "src.tools.self_healing.capture" in _RUNTIME_MODULES
    assert "src.tools.self_healing.buglog" in _RUNTIME_MODULES


def test_record_failure_files_a_browse_bug_under_browse(tmp_path) -> None:
    """The index scope follows the failure's stage, not a hard-coded 'fill'."""
    known = tmp_path / "known Bugs"
    known.mkdir(parents=True)
    (known / "bug_log.md").write_text(
        "# Bug Log\n\n| ID | Task / area | Symptom (short) | Status | Fix commit(s) |\n"
        "|----|-------------|-----------------|--------|---------------|\n\n"
        "## Template for new entries\n",
        encoding="utf-8",
    )
    captured = CapturedFailure(
        fingerprint="browsefingerprint",
        category="search_no_results",
        symptom="the job search returned no results",
        bundle_dir=str(tmp_path / "bundle"),
        evidence=FailureEvidence(
            stage="browse",
            error="browse: job search returned no results",
            captured_at="2026-10-27T06:26:33+00:00",
        ),
    )

    record_failure(captured, root=tmp_path)

    index = (known / "bug_log.md").read_text(encoding="utf-8")
    assert "Self-Healing — browse/search" in index
    assert "Self-Healing — fill" not in index
