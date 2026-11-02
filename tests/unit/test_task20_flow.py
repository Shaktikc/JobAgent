"""Validation skips bypass submission/self-healing and carry posting exclusions."""

from src.configuration import Settings
from src.graph import _route_after_fill, _route_after_match
from src.state import Task2Outcome, Task3Outcome, Task4Outcome, Task5Outcome
from src.state.validation import ValidationFailure, ValidationIssue
from src.tools.self_healing.fingerprint import classify_failure, fill_failure_reason, is_recoverable


def skipped_form():
    return Task4Outcome(
        validation=ValidationFailure(
            issues=[ValidationIssue(message="Invalid input")],
            logged=True,
            modal_closed=True,
            job_id="123",
            job_url="https://www.linkedin.com/jobs/view/123/",
        )
    )


def test_skipped_fill_routes_to_next_job_without_waiting_for_submit():
    assert _route_after_fill({"status": "skipped", "task4": skipped_form()}) == "next_job"
    assert _route_after_match({"status": "skipped"}) == "next_job"
    assert _route_after_fill({"status": "skipped", "errors": ["write failure"]}) == "cleanup"


def test_validation_is_not_a_structural_failure_or_submission():
    outcome = skipped_form()
    assert not fill_failure_reason(outcome)
    assert not outcome.awaiting_human_submit
    assert not is_recoverable(classify_failure(task4=outcome), outcome)
    outcome.validation.modal_closed = False
    outcome.validation.error = "log write failed"
    assert "log write failed" in fill_failure_reason(outcome)


async def test_fill_node_records_validation_skip_without_healing(monkeypatch):
    from src.nodes.fill import fill

    async def fake_fill(*args, **kwargs):
        return skipped_form(), Task5Outcome()

    monkeypatch.setattr("src.tools.browser.fill_application", fake_fill)
    update = await fill(
        {
            "dry_run": False,
            "browser_run_id": "run",
            "task3": Task3Outcome(selected_path="resume.txt"),
        }
    )
    assert update["status"] == "skipped"
    assert update["task20"].jobs_skipped == 1
    assert update["skipped_job_ids"] == ["123"]
    assert "self_healing" not in update and not update.get("errors")


async def test_next_node_passes_posting_ids_without_excluding_identical_titles(monkeypatch):
    from src.nodes.apply_loop import next_job
    from src.tools.linkedin_apply_loop import NextJobResult

    captured = {}

    async def fake_next(*args, **kwargs):
        captured.update(kwargs)
        return NextJobResult(reason="exhausted")

    monkeypatch.setattr("src.nodes.apply_loop.load_settings", lambda: Settings())
    monkeypatch.setattr("src.tools.linkedin_apply_loop.open_next_job", fake_next)
    await next_job(
        {
            "dry_run": False,
            "browser_run_id": "run",
            "status": "skipped",
            "task2": Task2Outcome(job_title="Engineer"),
            "task3": Task3Outcome(selected_path="resume.txt"),
            "task4": skipped_form(),
            "skipped_job_ids": ["123"],
        }
    )
    assert captured["skip_job_ids"] == ["123"]
    assert captured["skip_title"] == ""
