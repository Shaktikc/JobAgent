"""Exercise the context retry through the same per-step boundary as fill and recovery."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.configuration import LLMSettings, Settings
from src.nodes.fill import _decision_line
from src.state import FormField, JobAnswerContext, JobDescription, Task5Outcome
from src.tools.job_context_answers import build_fill_chooser, record_decision
from src.tools.linkedin_validation.required_answers import AnswerAttempts
from src.tools.token_usage import runtime

QUESTION = "Why are you interested in this role?*"
EVIDENCE = "Develop accessible interfaces."


def reply(answer="", evidence=EVIDENCE, job_specific=True):
    body = json.dumps(dict(
        job_specific=job_specific, answer=answer, sources=["job_description"], evidence=[evidence],
    ))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=body))])


@pytest.fixture
def setup(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, llm=LLMSettings(
        model="context-model", answers_model="store-model", api_key="test",
    ))
    client = MagicMock()
    client.with_options.return_value = client
    create = AsyncMock()
    client.chat.completions.create = create
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kwargs: client)
    context = JobAnswerContext(job_description=JobDescription(company="Acme", body=EVIDENCE),
                               resume_text="Frontend engineer")
    store = {"why did you like your old role": "stale prose"}
    chooser = build_fill_chooser(settings, store, context)
    return AnswerAttempts(settings, Task5Outcome(), chooser, AsyncMock(), None, store), create


async def test_second_context_read_fills_with_provenance(setup):
    attempts, create = setup
    create.side_effect = [reply(), reply("I want to develop accessible interfaces.")]
    before = runtime.tracker.snapshot().calls
    result = await attempts.choose(QUESTION, "textarea", [])
    assert result.decided and result.second_look and result.evidence == [EVIDENCE]
    assert runtime.tracker.snapshot().calls == before + 2
    first, second = [call.kwargs for call in create.await_args_list]
    assert first["model"] == second["model"] == "context-model"
    assert first["messages"][1] == second["messages"][1]
    assert "Independently re-read" in second["messages"][0]["content"]
    assert "stale prose" not in str(second)
    assert attempts.audit()[0].second_attempt_found and attempts.audit()[0].job_context_rejection
    field = FormField(question=QUESTION)
    record_decision(field, result)
    assert "second look" in _decision_line(field) and field.answer_source == "job_description"
    assert not attempts.settings.answers_file.exists()
    assert not attempts.settings.derived_answers_file.exists()
    attempts.asker.assert_not_awaited()


@pytest.mark.parametrize("retry", [
    reply("I joined an unrelated company.", "invented evidence"),
    reply(job_specific=False), TimeoutError(),
])
async def test_failed_retry_prompts_once_without_store_fallback(setup, retry):
    attempts, create = setup
    attempts.asker.return_value = None
    create.side_effect = [reply(), retry]
    for _ in range(2):
        decision = await attempts.choose(QUESTION, "textarea", [])
        assert not decision.decided
        await attempts.ask(QUESTION, {"type": "textarea"})
    assert create.await_count == 2
    attempts.asker.assert_awaited_once()
    assert attempts.audit()[0].second_attempted and not attempts.audit()[0].second_attempt_found
    assert "First pass and second look missed" in attempts.human.notes


async def test_deadline_cancels_stalled_context_retry(setup):
    attempts, create = setup
    attempts.settings.llm.timeout_seconds = 0.05
    async def stall(**kwargs):
        if create.await_count == 1:
            return reply()
        await asyncio.Event().wait()
    create.side_effect = stall
    decision = await asyncio.wait_for(attempts.choose(QUESTION, "textarea", []), 2)
    assert not decision.decided and "TimeoutError" in decision.rationale


@pytest.mark.parametrize("enabled,first_answer", [(False, ""), (True, EVIDENCE)])
async def test_no_retry_after_success_or_without_banner(setup, enabled, first_answer):
    attempts, create = setup
    attempts.settings.session.ask_human = enabled
    create.return_value = reply(first_answer)
    decision = await attempts.choose(QUESTION, "textarea", [])
    assert decision.decided == bool(first_answer)
    assert not attempts.audit()[0].second_attempted
    create.assert_awaited_once()
