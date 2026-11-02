"""Only a durable log and confirmed modal cleanup may become a clean skip."""

import json
from types import SimpleNamespace

import pytest

from src.configuration import Settings
from src.state import Task4Outcome
from src.state.validation import ValidationFailure, ValidationIssue
from src.tools.linkedin_validation.skip import persist_and_close, record_validation_skip


class Page:
    async def get_url(self):
        return "https://www.linkedin.com/jobs/view/123/?tracking=secret"


def rejected():
    return Task4Outcome(
        validation=ValidationFailure(
            issues=[ValidationIssue(question="Salary*", message="Invalid input")],
            correction_attempted=True,
            retry_count=1,
            correction_failure="validation persisted after correction",
        )
    )


async def test_persist_precedes_close_and_records_a_skip(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path)
    outcome = rejected()

    async def close(*args):
        records = json.loads((tmp_path / "invalid_input_skips.json").read_text())
        assert records[0]["job_url"] == "https://www.linkedin.com/jobs/view/123/"
        assert records[0]["retry_count"] == 1
        assert "value" not in records[0]
        return True

    monkeypatch.setattr("src.tools.linkedin_validation.skip.close_easy_apply_form", close)
    await persist_and_close(Page(), {}, outcome, settings, lambda _: None)
    update = record_validation_skip({}, outcome)
    assert update["status"] == "skipped"
    assert update["task20"].jobs_skipped == 1
    assert update["skipped_job_ids"] == ["123"]
    assert not outcome.submitted
    assert "task8" not in update and not update.get("errors")


async def test_write_failure_never_closes_or_counts_job(tmp_path, monkeypatch):
    from src.tools.linkedin_validation import skip

    def fail(*args):
        raise OSError("disk full")

    async def forbidden(*args):
        pytest.fail("must save the job link before closing")

    monkeypatch.setattr(skip, "append_skip", fail)
    monkeypatch.setattr(skip, "close_easy_apply_form", forbidden)
    outcome = rejected()
    await persist_and_close(Page(), {}, outcome, Settings(data_dir=tmp_path), lambda _: None)
    update = record_validation_skip({}, outcome)
    assert update["status"] == "failed"
    assert update["errors"] and "disk full" in update["errors"][0]
    assert "task20" not in update


async def test_close_failure_retains_logged_link_and_stops(tmp_path, monkeypatch):
    async def close(*args):
        return False

    monkeypatch.setattr("src.tools.linkedin_validation.skip.close_easy_apply_form", close)
    outcome = rejected()
    await persist_and_close(Page(), {}, outcome, Settings(data_dir=tmp_path), lambda _: None)
    assert outcome.validation.logged and not outcome.validation.skipped
    assert outcome.validation.job_url.endswith("/123/")
    assert record_validation_skip({}, outcome)["status"] == "failed"


async def test_missing_job_link_never_discards(tmp_path, monkeypatch):
    async def url():
        return "https://www.linkedin.com/jobs/search/"

    async def evaluate(script):
        return ""

    page = SimpleNamespace(get_url=url, evaluate=evaluate)
    outcome = rejected()
    await persist_and_close(page, {}, outcome, Settings(data_dir=tmp_path), lambda _: None)
    assert not outcome.validation.logged
    assert "direct job link" in outcome.validation.error
    assert not list(tmp_path.glob("*.json"))
