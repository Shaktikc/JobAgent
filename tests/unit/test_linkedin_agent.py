"""Unit tests for LinkedIn URL helpers and the agent read task (Task 17).

Pure only: no browser, no LLM. The read itself (structured output) is exercised by
the manual integration smoke, not here.
"""

from __future__ import annotations

import pytest

from src.nodes import discover
from src.tools import linkedin

JOB_URL = "https://www.linkedin.com/jobs/view/4012345678/"


def test_job_id_from_view_url() -> None:
    assert linkedin.job_id_from_url(JOB_URL) == "4012345678"


def test_job_id_from_search_url_current_job_id() -> None:
    url = "https://www.linkedin.com/jobs/search/?keywords=data&currentJobId=4012345678&refId=x"
    assert linkedin.job_id_from_url(url) == "4012345678"


def test_job_id_missing_raises() -> None:
    with pytest.raises(ValueError, match="cannot determine"):
        linkedin.job_id_from_url("https://www.linkedin.com/feed/")


def test_read_task_names_the_url_and_is_read_only() -> None:
    task = linkedin.build_read_job_task(JOB_URL)

    assert JOB_URL in task
    assert "Read only" in task
    assert "do not click Easy Apply" in task


def test_as_job_state_projects_the_extraction() -> None:
    extraction = linkedin.JobExtraction(
        title="Data Analyst",
        company="Acme",
        description="Numbers",
        easy_apply=True,
    )

    state = discover.as_job_state(extraction, url=JOB_URL)

    assert state["job_id"] == "4012345678"
    assert state["title"] == "Data Analyst"
    assert state["easy_apply"] is True


def test_ensure_easy_apply_rejects_external_apply() -> None:
    extraction = linkedin.JobExtraction(title="x", easy_apply=False)

    with pytest.raises(discover.NotEasyApplyError):
        discover.ensure_easy_apply(extraction, label=JOB_URL)
