"""Task 32: an initial scan with only blacklisted postings ends the run cleanly."""

from __future__ import annotations

from types import SimpleNamespace

from src import graph as graph_module
from src.nodes.browse import browse
from src.nodes.task_self_heal import task_failure_reason
from src.nodes.verify import verify
from src.state import JobDescription, Task1Outcome, Task2Outcome
from src.tools import browser as browser_tools
from src.tools.company_blacklist import NO_ELIGIBLE_JOB_REASON


def _task1() -> Task1Outcome:
    return Task1Outcome(
        logged_in=True,
        results_found=True,
        easy_apply_filter_selected=True,
        date_posted_filter_selected=True,
        date_posted_filter_value="past_24_hours",
    )


def _blacklisted_only() -> Task2Outcome:
    return Task2Outcome(
        jobs_seen=2,
        blacklisted_jobs_skipped=2,
        notes="skipped 2 job(s) from blacklisted companies",
    )


async def test_browse_stops_cleanly_when_only_blacklisted_jobs_remain(monkeypatch) -> None:
    async def fake_start_tasks(*args, **kwargs):
        result = SimpleNamespace(
            task1=_task1(), task2=_blacklisted_only(), job_description=JobDescription()
        )
        return result, "run-1"

    monkeypatch.setattr(browser_tools, "start_tasks", fake_start_tasks, raising=False)
    update = await browse(
        {"dry_run": False, "url": "https://www.linkedin.com/", "date_range": "past_24_hours"}
    )

    assert update["status"] == "stopped"
    assert not update.get("errors")
    assert update["task8"].stopped_reason == NO_ELIGIBLE_JOB_REASON
    assert any("blacklisted_skipped=2" in line for line in update["log"])
    # The guard must not self-heal a clean end, and the graph releases the session.
    assert task_failure_reason("browse", update) == ""
    assert graph_module._route_after_browse({**update, "dry_run": False}) == "cleanup"

    final = verify({**update, "dry_run": False, "date_range": "past_24_hours"})
    assert final["status"] == "done"


def test_no_job_without_blacklist_skips_is_still_a_hard_stop() -> None:
    update = {"task1": _task1(), "task2": Task2Outcome(jobs_seen=2)}
    assert task_failure_reason("browse", update) == "browse: no Easy Apply job was selected"
