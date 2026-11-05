"""Skip evidence identifies attempted sources without including rejected answers."""

import json

from src.configuration import Settings
from src.state import Task4Outcome
from src.state.validation import RequiredAnswerAttempt, ValidationFailure, ValidationIssue
from src.tools.linkedin_validation import skip


async def test_required_answer_attempts_are_saved_before_the_form_closes(tmp_path, monkeypatch):
    async def identity(*args):
        return "123", "https://www.linkedin.com/jobs/view/123/"

    async def close(*args):
        data = json.loads((tmp_path / "invalid_input_skips.json").read_text())
        assert data[0]["required_answer_attempts"] == [
            {
                "question": "Tools*",
                "automatic_attempted": True,
                "human_prompted": True,
                "failure": "human skipped",
            }
        ]
        assert data[0]["errors"] == [{"question": "Tools*", "message": "This field is required"}]
        assert data[0]["job_url"].endswith("/123/")
        assert "value" not in json.dumps(data)
        return True

    monkeypatch.setattr(skip, "current_job_link", identity)
    monkeypatch.setattr(skip, "close_easy_apply_form", close)
    outcome = Task4Outcome(
        validation=ValidationFailure(
            issues=[ValidationIssue(question="Tools*", message="This field is required")],
            required_answer_attempts=[
                RequiredAnswerAttempt(
                    question="Tools*",
                    automatic_attempted=True,
                    human_prompted=True,
                    failure="human skipped",
                )
            ],
        )
    )
    await skip.persist_and_close(None, {}, outcome, Settings(data_dir=tmp_path), lambda _: None)
    assert skip.record_validation_skip({}, outcome)["status"] == "skipped"
    assert not outcome.submitted
