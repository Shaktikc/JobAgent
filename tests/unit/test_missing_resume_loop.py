import importlib

from src.configuration import Settings
from src.graph import _route_after_fill
from src.nodes.apply_loop import next_job
from src.nodes.verify import verify
from src.state import (
    ApplyState,
    Task1Outcome,
    Task2Outcome,
    Task3Outcome,
    Task4Outcome,
    Task5Outcome,
)
from src.tools import browser
from src.tools.linkedin_apply_loop import NextJobResult


async def test_missing_resume_skips_one_posting_and_scans_to_exhaustion(monkeypatch, tmp_path):
    fill_node = importlib.import_module("src.nodes.fill")
    settings = Settings()
    settings.self_healing.enabled = False
    monkeypatch.setattr(fill_node, "load_settings", lambda: settings)
    monkeypatch.setattr("src.nodes.apply_loop.load_settings", lambda: settings)
    resume = tmp_path / "resume.txt"
    resume.write_text("Engineer", encoding="utf8")

    async def no_attachment(*args, **kwargs):
        return Task4Outcome(
            form_open=True,
            page_url="https://www.linkedin.com/jobs/view/123/",
            notes="no resume control found on this form step",
        ), Task5Outcome()

    async def exhausted(*args, **kwargs):
        assert kwargs["close_form"]
        assert kwargs["skip_job_ids"] == ["123"]
        assert kwargs["skip_title"] == ""
        return NextJobResult(reason="no unapplied jobs remain")

    monkeypatch.setattr(browser, "fill_application", no_attachment)
    monkeypatch.setattr("src.tools.linkedin_apply_loop.open_next_job", exhausted)
    state = ApplyState(
        dry_run=False,
        submission_mode="auto",
        browser_run_id="test",
        task1=Task1Outcome(
            logged_in=True,
            results_found=True,
            easy_apply_filter_selected=True,
            date_posted_filter_selected=True,
            date_posted_filter_value="past_24_hours",
        ),
        task2=Task2Outcome(job_title="Engineer", job_selected=True, easy_apply_button_found=True),
        task3=Task3Outcome(selected_path=str(resume)),
    )
    state.update(await fill_node.fill(state))
    assert _route_after_fill(state) == "next_job"
    assert state["task8"].jobs_applied == 0
    state.update(await next_job(state))
    assert verify(state)["status"] == "done"
