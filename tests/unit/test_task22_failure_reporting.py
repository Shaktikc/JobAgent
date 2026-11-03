"""Unconfirmed applications require review and retain private diagnostic evidence."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.configuration import Settings
from src.nodes.verify import verify
from src.state import Task8Outcome
from src.tools.linkedin_submission_evidence import capture_submission_failure


@pytest.mark.parametrize("status", ["blocked", "unconfirmed", "closed", "interrupted"])
def test_uncertain_automatic_submission_is_not_reported_as_done(status):
    update = verify({"dry_run": False, "submission_mode": "auto", "task8": Task8Outcome(
        last_submission_status=status, stopped_reason="review manually", jobs_applied=0,
    )})
    assert update["status"] == "needs_review"
    assert "confirmed submissions this run=0" in update["log"][1]


@pytest.mark.asyncio
async def test_failure_evidence_excludes_answers_and_confirmation_prose(tmp_path):
    async def evaluate(_):
        return json.dumps({"form_found": True, "buttons": [{"label": "Submit application"}]})
    page = SimpleNamespace(evaluate=evaluate)
    path = await capture_submission_failure(
        page, Settings(data_dir=tmp_path), "not confirmed",
        initial={"form_open": True, "confirmation": "Private answer must not be copied"},
        current={"form_open": False},
    )
    text = Path(path).read_text(encoding="utf-8")
    assert "Private answer" not in text
    report = json.loads(text)
    assert report["before"]["confirmation"] is True
    assert report["after"]["form_open"] is False
    assert report["dom"]["form_found"] is True
