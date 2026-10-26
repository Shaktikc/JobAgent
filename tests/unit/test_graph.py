"""End-to-end tests for the agent graph (offline: no browser, no network)."""

from __future__ import annotations

import asyncio

import pytest

from src.configuration import SessionSettings, Settings
from src.graph import (
    _route_after_browse,
    _route_after_fill,
    _route_after_ingest,
    _route_after_match,
    _route_after_next_job,
    _route_after_submit,
    graph,
)
from src.nodes.apply_loop import await_submit, next_job
from src.nodes.cleanup import cleanup
from src.nodes.fill import fill
from src.nodes.match import match
from src.nodes.verify import verify
from src.state import (
    DEFAULT_LOGIN_URL,
    ApplyState,
    FormField,
    JobDescription,
    ResumeCandidate,
    Task1Outcome,
    Task2Outcome,
    Task3Outcome,
    Task4Outcome,
    Task5Outcome,
    Task8Outcome,
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
            ResumeCandidate(path="resumes/a.pdf", summary="Python engineer", described=True)
        ],
        selected_path="resumes/a.pdf",
        rationale="the LLM chose the best match",
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
        reached_terminal_step=True,
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


def test_match_node_selects_best_resume(tmp_path, monkeypatch) -> None:
    import src.tools.linkedin_best_matching_resume as resume_tools

    async def fake_ensure(description, resumes_dir, settings, page=None, notify=None, **kwargs):
        return Task3Outcome(
            job_description=description,
            resumes_dir=str(resumes_dir),
            resumes_found=2,
            candidates=[
                ResumeCandidate(path="resumes/python.txt", summary="Python", described=True),
                ResumeCandidate(path="resumes/frontend.txt", summary="Frontend", described=True),
            ],
            selected_path="resumes/python.txt",
            rationale="the LLM's reason",
        )

    monkeypatch.setattr(resume_tools, "ensure_resume", fake_ensure)
    state = ApplyState(
        dry_run=False,
        resumes_dir=str(tmp_path),
        job_description=JobDescription(
            title="Senior Python Engineer",
            body="We need Python, AWS and Docker. 5+ years required.",
        ),
    )
    result = asyncio.run(match(state))

    assert result["status"] == "matched"
    assert result["task3"].selected_path == "resumes/python.txt"
    assert result["task3"].resumes_found == 2
    assert len(result["task3"].candidates) == 2
    assert result["task3"].rationale
    assert "errors" not in result


def test_match_node_fails_when_the_description_was_not_read(tmp_path) -> None:
    """An unread description is a failure, not a "no resume matched" fallback.

    Choosing a resume (or asking the human) with no description would poison the
    remembered-resume library, so the run stops with a clear error instead.
    """
    state = ApplyState(
        dry_run=False,
        resumes_dir=str(tmp_path),
        job_description=JobDescription(),
    )
    result = asyncio.run(match(state))

    assert result["status"] == "failed"
    assert result["errors"]
    assert "task3" not in result


def test_match_node_reports_empty_folder(tmp_path) -> None:
    state = ApplyState(
        dry_run=False,
        resumes_dir=str(tmp_path),
        job_description=JobDescription(title="Engineer", body="Python"),
    )
    result = asyncio.run(match(state))

    assert result["task3"].resumes_found == 0
    assert result["task3"].selected_path is None
    assert result["errors"]


def test_match_node_skips_on_dry_run() -> None:
    result = asyncio.run(match(ApplyState(dry_run=True)))
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


def test_fill_node_does_not_fail_on_an_optional_unfilled_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only required fields make the fill fail; log the optional one instead."""
    import src.tools.browser as browser_tools

    outcome = _task4_ok()
    outcome.fields = [
        FormField(
            question="Optional question",
            known=True,
            filled=False,
            required=False,
            error="no option matched the answer",
        )
    ]

    async def fake_fill(run_id, resume_path, settings=None, progress=None):
        return outcome, _task5_ok()

    monkeypatch.setattr(browser_tools, "fill_application", fake_fill)
    state = ApplyState(dry_run=False, browser_run_id="run-1", task3=_task3_ok())

    result = asyncio.run(fill(state))

    assert not result.get("errors")
    assert any("known but not filled" in entry for entry in result["log"])


def test_fill_node_names_the_required_fields_that_block_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.tools.browser as browser_tools

    outcome = _task4_ok()
    outcome.fields = [
        FormField(
            question="Required question",
            known=True,
            filled=False,
            required=True,
            error="field element not found",
        ),
        FormField(question="Unanswered question", known=False, required=True),
    ]

    async def fake_fill(run_id, resume_path, settings=None, progress=None):
        return outcome, _task5_ok()

    monkeypatch.setattr(browser_tools, "fill_application", fake_fill)
    state = ApplyState(dry_run=False, browser_run_id="run-1", task3=_task3_ok())

    result = asyncio.run(fill(state))

    assert result["errors"]
    message = " ".join(result["errors"])
    assert "required fields were not filled" in message
    assert "Required question" in message
    assert "required questions are unanswered" in message
    assert "Unanswered question" in message


def test_cleanup_node_is_noop_without_a_run() -> None:
    assert asyncio.run(cleanup(ApplyState(dry_run=False))) == {}


def test_cleanup_leaves_browser_open_for_the_human_at_the_terminal_step(monkeypatch) -> None:
    """At the last step the browser is released to the human, not closed."""
    import src.tools.browser as browser_tools

    calls: dict = {}

    async def fake_release(run_id, task4=None, settings=None, progress=None):
        calls["released"] = run_id
        calls["task4"] = task4
        return "human"

    monkeypatch.setattr(browser_tools, "release_run", fake_release)
    state = ApplyState(
        dry_run=False,
        browser_run_id="run-1",
        task4=Task4Outcome(form_open=True, reached_terminal_step=True),
    )

    result = asyncio.run(cleanup(state))

    assert calls["released"] == "run-1"
    assert calls["task4"].awaiting_human_submit is True
    assert result["log"] == ["cleanup: browser left open for the human"]


def test_cleanup_logs_a_wait_timeout(monkeypatch) -> None:
    import src.tools.browser as browser_tools

    async def fake_release(run_id, task4=None, settings=None, progress=None):
        return "timeout"

    monkeypatch.setattr(browser_tools, "release_run", fake_release)
    state = ApplyState(
        dry_run=False,
        browser_run_id="run-1",
        task4=Task4Outcome(form_open=True, reached_terminal_step=True),
    )

    result = asyncio.run(cleanup(state))

    assert result["log"] == ["cleanup: browser left open for the human; wait ended"]


def test_cleanup_releases_the_run_when_not_at_the_terminal_step(monkeypatch) -> None:
    import src.tools.browser as browser_tools

    calls: dict = {}

    async def fake_release(run_id, task4=None, settings=None, progress=None):
        calls["released"] = run_id
        calls["task4"] = task4
        return "closed"

    monkeypatch.setattr(browser_tools, "release_run", fake_release)
    state = ApplyState(
        dry_run=False,
        browser_run_id="run-1",
        task4=Task4Outcome(form_open=True, reached_terminal_step=False),
    )

    result = asyncio.run(cleanup(state))

    assert calls["released"] == "run-1"
    assert calls["task4"].awaiting_human_submit is False
    assert result["log"] == ["cleanup: browser left open (run released)"]


# --- Task 8: the submit-and-repeat loop -----------------------------------


def _settings(**session) -> Settings:
    return Settings(session=SessionSettings(**session))


def test_route_after_fill() -> None:
    # Only wait for the human when the walk stopped at the terminal step.
    assert _route_after_fill({"errors": ["fill: boom"]}) == "cleanup"
    assert _route_after_fill({}) == "cleanup"
    assert _route_after_fill({"task4": Task4Outcome(reached_terminal_step=False)}) == "cleanup"
    assert _route_after_fill({"task4": Task4Outcome(reached_terminal_step=True)}) == "await_submit"
    # An agent submit (never expected) does not wait for the human.
    assert (
        _route_after_fill({"task4": Task4Outcome(reached_terminal_step=True, submitted=True)})
        == "cleanup"
    )


def test_route_after_submit() -> None:
    assert _route_after_submit({}) == "next_job"
    assert _route_after_submit({"errors": ["await_submit: boom"]}) == "cleanup"
    assert _route_after_submit({"task8": Task8Outcome(stopped_reason="cap")}) == "cleanup"


def test_route_after_next_job() -> None:
    assert _route_after_next_job({}) == "match"
    assert _route_after_next_job({"errors": ["next_job: boom"]}) == "cleanup"
    assert _route_after_next_job({"task8": Task8Outcome(stopped_reason="none")}) == "cleanup"


def test_graph_has_the_task8_loop() -> None:
    view = graph.get_graph()
    assert {"await_submit", "next_job"} <= set(view.nodes)
    edges = {(edge.source, edge.target) for edge in view.edges}
    assert ("fill", "await_submit") in edges
    assert ("await_submit", "next_job") in edges
    assert ("next_job", "match") in edges  # loops back to matching for the next job


def test_await_submit_skips_on_dry_run() -> None:
    result = asyncio.run(await_submit(ApplyState(dry_run=True)))
    assert result["status"] == "submitted"
    assert "task8" not in result


def test_await_submit_fails_without_a_session() -> None:
    result = asyncio.run(await_submit(ApplyState(dry_run=False)))
    assert result["status"] == "failed"
    assert result["errors"]


def test_await_submit_records_a_submitted_job(monkeypatch) -> None:
    import src.nodes.apply_loop as apply_loop
    import src.tools.linkedin_apply_loop as loop

    async def fake_wait(run_id, settings=None, progress=None, title=""):
        assert title == "Data Engineer"
        return "submitted"

    monkeypatch.setattr(loop, "await_human_submit", fake_wait)
    monkeypatch.setattr(apply_loop, "load_settings", lambda: _settings(max_jobs_per_run=5))
    state = ApplyState(
        dry_run=False,
        browser_run_id="run-1",
        task2=Task2Outcome(job_index=2, job_title="Data Engineer"),
        task3=_task3_ok(),
        job_description=JobDescription(title="Data Engineer", company="Acme"),
    )

    result = asyncio.run(await_submit(state))

    task8 = result["task8"]
    assert task8.iterations == 1
    assert task8.jobs_applied == 1
    assert task8.max_jobs == 5
    assert task8.stopped_reason == ""  # under the cap: the loop continues
    assert task8.jobs[0].title == "Data Engineer"
    assert task8.jobs[0].company == "Acme"
    assert task8.jobs[0].resume_path == "resumes/a.pdf"
    assert task8.jobs[0].outcome == "submitted"


def test_await_submit_stops_at_the_jobs_cap(monkeypatch) -> None:
    import src.nodes.apply_loop as apply_loop
    import src.tools.linkedin_apply_loop as loop

    async def fake_wait(run_id, settings=None, progress=None, title=""):
        return "submitted"

    monkeypatch.setattr(loop, "await_human_submit", fake_wait)
    monkeypatch.setattr(apply_loop, "load_settings", lambda: _settings(max_jobs_per_run=1))
    state = ApplyState(
        dry_run=False,
        browser_run_id="run-1",
        task2=Task2Outcome(job_title="Backend Engineer"),
        task3=_task3_ok(),
        job_description=JobDescription(title="Backend Engineer", company="Acme"),
    )

    result = asyncio.run(await_submit(state))

    assert result["task8"].jobs_applied == 1
    assert result["task8"].stopped_reason == "reached the jobs-per-run cap (1)"


def test_await_submit_stops_when_the_human_closes(monkeypatch) -> None:
    import src.nodes.apply_loop as apply_loop
    import src.tools.linkedin_apply_loop as loop

    async def fake_wait(run_id, settings=None, progress=None, title=""):
        return "closed"

    monkeypatch.setattr(loop, "await_human_submit", fake_wait)
    monkeypatch.setattr(apply_loop, "load_settings", lambda: _settings(max_jobs_per_run=5))
    state = ApplyState(
        dry_run=False,
        browser_run_id="run-1",
        task2=Task2Outcome(job_title="Backend Engineer"),
        task3=_task3_ok(),
        job_description=JobDescription(title="Backend Engineer", company="Acme"),
    )

    result = asyncio.run(await_submit(state))

    assert result["task8"].jobs_applied == 0
    assert result["task8"].stopped_reason == "the human closed the browser"


def test_await_submit_stops_on_a_timeout(monkeypatch) -> None:
    import src.nodes.apply_loop as apply_loop
    import src.tools.linkedin_apply_loop as loop

    async def fake_wait(run_id, settings=None, progress=None, title=""):
        return "timeout"

    monkeypatch.setattr(loop, "await_human_submit", fake_wait)
    monkeypatch.setattr(apply_loop, "load_settings", lambda: _settings(max_jobs_per_run=5))
    state = ApplyState(
        dry_run=False,
        browser_run_id="run-1",
        task2=Task2Outcome(job_title="Backend Engineer"),
        task3=_task3_ok(),
        job_description=JobDescription(title="Backend Engineer", company="Acme"),
    )

    result = asyncio.run(await_submit(state))

    assert result["task8"].stopped_reason == "timed out waiting for the human to submit"


def test_next_job_opens_the_next_job(monkeypatch) -> None:
    import src.nodes.apply_loop as apply_loop
    import src.tools.linkedin_apply_loop as loop

    captured: dict = {}

    async def fake_open(run_id, settings=None, progress=None, skip_title=""):
        captured["skip_title"] = skip_title
        return loop.NextJobResult(
            opened=True,
            task2=Task2Outcome(
                job_title="QA Engineer", easy_apply_clicked=True, application_form_opened=True
            ),
            description=JobDescription(title="QA Engineer", company="Acme"),
        )

    monkeypatch.setattr(loop, "open_next_job", fake_open)
    monkeypatch.setattr(apply_loop, "load_settings", lambda: _settings())
    state = ApplyState(
        dry_run=False,
        browser_run_id="run-1",
        task2=Task2Outcome(job_title="Backend Engineer"),
    )

    result = asyncio.run(next_job(state))

    assert captured["skip_title"] == "Backend Engineer"
    assert result["status"] == "applied"
    assert result["task2"].job_title == "QA Engineer"
    assert result["job_description"].title == "QA Engineer"
    assert "task8" not in result


def test_next_job_stops_when_nothing_is_left(monkeypatch) -> None:
    import src.nodes.apply_loop as apply_loop
    import src.tools.linkedin_apply_loop as loop

    async def fake_open(run_id, settings=None, progress=None, skip_title=""):
        return loop.NextJobResult(
            opened=False,
            task2=Task2Outcome(jobs_seen=2, applied_jobs_skipped=2),
            reason="every job on every results page is already Applied",
        )

    monkeypatch.setattr(loop, "open_next_job", fake_open)
    monkeypatch.setattr(apply_loop, "load_settings", lambda: _settings())
    state = ApplyState(
        dry_run=False,
        browser_run_id="run-1",
        task2=Task2Outcome(job_title="Backend Engineer"),
    )

    result = asyncio.run(next_job(state))

    assert result["status"] == "stopped"
    assert result["task8"].stopped_reason == "every job on every results page is already Applied"
    # The last successfully opened job is kept for ``verify``.
    assert "task2" not in result


def test_verify_passes_when_the_task8_loop_stopped_cleanly() -> None:
    state = ApplyState(
        dry_run=False,
        task1=_task1_ok(),
        task2=_task2_ok(),
        task3=_task3_ok(),
        task4=_task4_ok(),
        task8=Task8Outcome(jobs_applied=2, stopped_reason="reached the jobs-per-run cap (2)"),
    )

    result = verify(state)

    assert result["status"] == "done"
    assert any("Task 8 loop submitted 2 job(s)" in line for line in result["log"])


def test_verify_fails_when_task8_has_no_stop_reason() -> None:
    state = ApplyState(
        dry_run=False,
        task1=_task1_ok(),
        task2=_task2_ok(),
        task3=_task3_ok(),
        task4=_task4_ok(),
        task8=Task8Outcome(jobs_applied=1),
    )
    assert verify(state)["status"] == "failed"


def test_cleanup_closes_directly_when_the_task8_loop_ran(monkeypatch) -> None:
    import src.tools.browser as browser_tools

    calls: dict = {}

    async def fake_close(run_id):
        calls["closed"] = run_id

    async def fake_release(run_id, task4=None, settings=None, progress=None):
        calls["released"] = run_id
        return "closed"

    monkeypatch.setattr(browser_tools, "close_run", fake_close)
    monkeypatch.setattr(browser_tools, "release_run", fake_release)
    state = ApplyState(
        dry_run=False,
        browser_run_id="run-1",
        task4=Task4Outcome(form_open=True, reached_terminal_step=True),
        task8=Task8Outcome(stopped_reason="reached the jobs-per-run cap (1)"),
    )

    result = asyncio.run(cleanup(state))

    # The loop already waited for the human per job; cleanup just closes once.
    assert calls["closed"] == "run-1"
    assert "released" not in calls
    assert result["log"] == ["cleanup: browser left open (Task 8 loop finished)"]
