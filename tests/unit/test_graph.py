"""End-to-end tests for the agent graph (offline: no browser, no network)."""

from __future__ import annotations

import asyncio

import pytest

from src.graph import (
    _route_after_browse,
    _route_after_ingest,
    _route_after_match,
    graph,
)
from src.nodes.cleanup import cleanup
from src.nodes.fill import fill
from src.nodes.match import match
from src.nodes.verify import verify
from src.state import (
    DEFAULT_LOGIN_URL,
    ApplyState,
    JobDescription,
    ResumeCandidate,
    Task1Outcome,
    Task2Outcome,
    Task3Outcome,
    Task4Outcome,
    Task5Outcome,
    new_state,
)


def _run(**kwargs):
    return asyncio.run(graph.ainvoke(new_state(**kwargs)))


def _task1_ok() -> Task1Outcome:
    return Task1Outcome(
        logged_in=True,
        results_found=True,
        results_count=25,
        easy_apply_filter_selected=True,
    )


def _task2_ok() -> Task2Outcome:
    return Task2Outcome(
        jobs_seen=25,
        job_index=0,
        job_title="Backend Engineer",
        easy_apply_clicked=True,
        application_form_opened=True,
    )


def _task3_ok() -> Task3Outcome:
    description = JobDescription(title="Senior Python Engineer", body="Python, AWS, Docker")
    return Task3Outcome(
        job_description=description,
        resumes_dir="resumes",
        resumes_found=1,
        candidates=[
            ResumeCandidate(path="resumes/a.pdf", score=9.0, rationale="shared skills: python")
        ],
        selected_path="resumes/a.pdf",
        selected_score=9.0,
        rationale="shared skills: python",
    )


def _task4_ok() -> Task4Outcome:
    return Task4Outcome(
        form_open=True,
        fields_enumerated=3,
        known_fields=2,
        filled_fields=2,
        resume_attached=True,
        resume_selection="listed",
        resume_path="resumes/a.pdf",
    )


def _task5_ok() -> Task5Outcome:
    return Task5Outcome(enabled=True, asked=1, answered=1, answered_questions=["City"])


def test_new_state_defaults_match_task_inputs() -> None:
    state = new_state()
    assert state["url"] == DEFAULT_LOGIN_URL
    assert state["search_query"] == "software engineer"
    assert state["dry_run"] is True
    assert state["resumes_dir"] == ""


def test_dry_run_completes_without_launching_a_browser() -> None:
    state = _run(dry_run=True)

    assert state["status"] == "done"
    assert state.get("task1") is None
    assert state.get("task2") is None
    assert state.get("task3") is None
    assert state.get("task4") is None
    assert state["errors"] == []
    assert any("dry-run" in entry for entry in state["log"])


def test_invalid_url_fails_before_the_browser_node() -> None:
    state = _run(url="https://example.com/login", dry_run=True)

    assert state["status"] == "failed"
    assert state["errors"]
    assert state.get("task1") is None


def test_empty_url_fails() -> None:
    state = _run(url="", dry_run=True)
    assert state["status"] == "failed"


def test_empty_query_fails() -> None:
    state = _run(search_query="   ", dry_run=True)
    assert state["status"] == "failed"
    assert any("search query" in error for error in state["errors"])


def test_route_after_ingest() -> None:
    assert _route_after_ingest({"status": "failed"}) == "end"
    assert _route_after_ingest({"status": "logging_in"}) == "browse"
    assert _route_after_ingest({}) == "browse"


def test_route_after_browse() -> None:
    # A dry run never reaches the matcher.
    assert _route_after_browse({"dry_run": True}) == "verify"
    # Errors skip resume matching but still release the session.
    assert _route_after_browse({"dry_run": False, "errors": ["browse: boom"]}) == "cleanup"
    # A successful browse proceeds to matching.
    assert _route_after_browse({"dry_run": False}) == "match"


def test_route_after_match() -> None:
    assert _route_after_match({"errors": ["match: no resumes"]}) == "cleanup"
    assert _route_after_match({}) == "fill"


def test_verify_passes_when_all_criteria_are_met() -> None:
    state = ApplyState(
        dry_run=False,
        task1=_task1_ok(),
        task2=_task2_ok(),
        task3=_task3_ok(),
        task4=_task4_ok(),
    )
    assert verify(state) == {
        "status": "done",
        "log": [
            "verify: logged in, search returned results, Easy Apply filter selected, "
            "job Easy Apply form opened, best-matching resume selected, "
            "form filled and resume attached (not submitted)"
        ],
    }


def test_verify_fails_when_filter_is_not_selected() -> None:
    state = ApplyState(
        dry_run=False,
        task1=Task1Outcome(logged_in=True, results_found=True, easy_apply_filter_selected=False),
        task2=_task2_ok(),
        task3=_task3_ok(),
        task4=_task4_ok(),
    )
    result = verify(state)
    assert result["status"] == "failed"
    assert result["errors"]


def test_verify_fails_when_task2_is_missing() -> None:
    state = ApplyState(dry_run=False, task1=_task1_ok(), task3=_task3_ok(), task4=_task4_ok())
    assert verify(state)["status"] == "failed"


def test_verify_fails_when_easy_apply_form_does_not_open() -> None:
    state = ApplyState(
        dry_run=False,
        task1=_task1_ok(),
        task2=Task2Outcome(easy_apply_clicked=True, application_form_opened=False),
        task3=_task3_ok(),
        task4=_task4_ok(),
    )
    assert verify(state)["status"] == "failed"


def test_verify_fails_when_task3_is_missing() -> None:
    state = ApplyState(dry_run=False, task1=_task1_ok(), task2=_task2_ok(), task4=_task4_ok())
    assert verify(state)["status"] == "failed"


def test_verify_fails_when_task4_is_missing() -> None:
    state = ApplyState(dry_run=False, task1=_task1_ok(), task2=_task2_ok(), task3=_task3_ok())
    assert verify(state)["status"] == "failed"


def test_verify_fails_when_resume_not_attached() -> None:
    task4 = _task4_ok()
    task4.resume_attached = False
    state = ApplyState(
        dry_run=False, task1=_task1_ok(), task2=_task2_ok(), task3=_task3_ok(), task4=task4
    )
    assert verify(state)["status"] == "failed"


def test_verify_fails_when_known_field_not_filled() -> None:
    task4 = _task4_ok()
    task4.known_fields = 3
    task4.filled_fields = 2
    state = ApplyState(
        dry_run=False, task1=_task1_ok(), task2=_task2_ok(), task3=_task3_ok(), task4=task4
    )
    assert verify(state)["status"] == "failed"


def test_verify_fails_when_submit_was_clicked() -> None:
    task4 = _task4_ok()
    task4.submitted = True
    state = ApplyState(
        dry_run=False, task1=_task1_ok(), task2=_task2_ok(), task3=_task3_ok(), task4=task4
    )
    assert verify(state)["status"] == "failed"


def test_verify_fails_when_no_resume_selected() -> None:
    task3 = _task3_ok()
    task3.selected_path = None
    state = ApplyState(
        dry_run=False, task1=_task1_ok(), task2=_task2_ok(), task3=task3, task4=_task4_ok()
    )
    assert verify(state)["status"] == "failed"


def test_verify_fails_when_description_was_not_read() -> None:
    task3 = _task3_ok()
    task3.job_description = JobDescription()
    state = ApplyState(
        dry_run=False, task1=_task1_ok(), task2=_task2_ok(), task3=task3, task4=_task4_ok()
    )
    assert verify(state)["status"] == "failed"


def test_verify_reports_errors_first() -> None:
    state = ApplyState(dry_run=False, errors=["browse: boom"])
    assert verify(state)["status"] == "failed"


def test_verify_passes_when_human_questions_were_resolved() -> None:
    state = ApplyState(
        dry_run=False,
        task1=_task1_ok(),
        task2=_task2_ok(),
        task3=_task3_ok(),
        task4=_task4_ok(),
        task5=_task5_ok(),
    )
    assert verify(state)["status"] == "done"


def test_verify_fails_when_a_human_question_is_unresolved() -> None:
    # asked=2 but only one resolved answer/skip/timeout: Task 5 is incomplete.
    task5 = Task5Outcome(enabled=True, asked=2, answered=1)
    state = ApplyState(
        dry_run=False,
        task1=_task1_ok(),
        task2=_task2_ok(),
        task3=_task3_ok(),
        task4=_task4_ok(),
        task5=task5,
    )
    assert verify(state)["status"] == "failed"


def test_match_node_selects_best_resume(tmp_path) -> None:
    (tmp_path / "python.txt").write_text(
        "Senior Software Engineer. Python, AWS, Docker, Kubernetes, 8 years.", encoding="utf-8"
    )
    (tmp_path / "frontend.txt").write_text(
        "Frontend developer. React, CSS, HTML, 2 years.", encoding="utf-8"
    )

    state = ApplyState(
        dry_run=False,
        resumes_dir=str(tmp_path),
        job_description=JobDescription(
            title="Senior Python Engineer",
            body="We need Python, AWS and Docker. 5+ years required.",
        ),
    )
    result = match(state)

    assert result["status"] == "matched"
    assert result["task3"].selected_path.endswith("python.txt")
    assert result["task3"].resumes_found == 2
    assert len(result["task3"].candidates) == 2
    assert result["task3"].rationale
    assert "errors" not in result


def test_match_node_reports_empty_folder(tmp_path) -> None:
    state = ApplyState(
        dry_run=False,
        resumes_dir=str(tmp_path),
        job_description=JobDescription(title="Engineer", body="Python"),
    )
    result = match(state)

    assert result["task3"].resumes_found == 0
    assert result["task3"].selected_path is None
    assert result["errors"]


def test_match_node_skips_on_dry_run() -> None:
    result = match(ApplyState(dry_run=True))
    assert result["status"] == "matched"
    assert "task3" not in result
    assert any("dry-run" in entry for entry in result["log"])


def test_fill_node_skips_on_dry_run() -> None:
    result = asyncio.run(fill(ApplyState(dry_run=True)))
    assert result["status"] == "filled"
    assert "task4" not in result
    assert any("dry-run" in entry for entry in result["log"])


def test_fill_node_fails_without_session_or_resume() -> None:
    result = asyncio.run(fill(ApplyState(dry_run=False)))
    assert result["status"] == "failed"
    assert result["errors"]


def test_fill_node_records_task5(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fill node stores the Task 5 outcome returned with the Task 4 fill."""
    import src.tools.browser as browser_tools

    async def fake_fill(run_id, resume_path, settings=None, progress=None):
        return _task4_ok(), _task5_ok()

    monkeypatch.setattr(browser_tools, "fill_application", fake_fill)
    state = ApplyState(dry_run=False, browser_run_id="run-1", task3=_task3_ok())

    result = asyncio.run(fill(state))

    assert result["status"] == "filled"
    assert result["task4"].form_open is True
    assert result["task5"].answered == 1
    assert result["task5"].answered_questions == ["City"]
    assert any("task5" in entry for entry in result["log"])


def test_cleanup_node_is_noop_without_a_run() -> None:
    assert asyncio.run(cleanup(ApplyState(dry_run=False))) == {}
