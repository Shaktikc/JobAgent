"""Request-level coverage for independent resume, store, and context models."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.configuration import LLMSettings, Settings
from src.main import _log_models
from src.state import JobAnswerContext, JobDescription
from src.tools.job_context_answers import build_fill_chooser
from src.tools.llm_answer_reasoning import build_reasoning_answer_chooser
from src.tools.llm_answers import build_answer_chooser
from src.tools.resume_descriptions import (
    ResumeDescription,
    ResumeDescriptionError,
    describe_resume,
    pick_best_resume,
)
from src.tools.resume_intake import process_new_resumes

AI_KEY = "how many years of work experience do you have with artificial intelligence (ai)"
STORE = {AI_KEY: "5"}


class RecordingClient:
    def __init__(self, reply, *, error=None):
        self.reply = json.dumps(reply)
        self.error = error
        self.calls = []
        self.chat = self.completions = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))]
        )


@pytest.fixture
def settings(tmp_path):
    return Settings(
        llm=LLMSettings(
            api_key="test-secret", model="provider/general",
            resume_model="provider/resumes", answers_model="provider/answers",
            transport_retries=0,
        ),
        data_dir=tmp_path,
    )


def install_client(monkeypatch, client):
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kwargs: client)


@pytest.mark.parametrize("general_model", [None, "provider/general"])
async def test_resume_description_and_selection_send_the_resume_model(
    settings, monkeypatch, general_model,
):
    settings.llm.model = general_model
    client = RecordingClient({"summary": "Python engineer", "skills": ["Python"]})
    install_client(monkeypatch, client)
    profile = await describe_resume("r.txt", settings, extract_text=lambda _: "Python engineer")
    client.reply = '{"choice":"c1","ratings":{"c1":"strong"},"rationale":"Python"}'
    match = await pick_best_resume(
        JobDescription(title="Python engineer"), [("r.txt", profile)], settings,
    )
    assert match.selected_path == "r.txt"
    assert [call["model"] for call in client.calls] == ["provider/resumes"] * 2
    assert settings.llm.model == general_model


async def test_new_resume_intake_uses_the_shared_resume_override(settings, monkeypatch, tmp_path):
    settings.llm.model = None
    client = RecordingClient({"summary": "Python engineer", "skills": ["Python"]})
    install_client(monkeypatch, client)
    pool = tmp_path / "resumes"
    intake = pool / "new"
    intake.mkdir(parents=True)
    (intake / "engineer.txt").write_text("Python engineer", encoding="utf-8")

    outcome = await process_new_resumes(pool, intake, settings)

    assert outcome.ok and outcome.described == 1 and outcome.moved == 1
    assert (pool / "engineer.txt").exists()
    assert not (intake / "engineer.txt").exists()
    assert [call["model"] for call in client.calls] == ["provider/resumes"]


@pytest.mark.parametrize("builder", [build_reasoning_answer_chooser, build_answer_chooser])
async def test_store_choosers_send_the_answer_model(settings, monkeypatch, builder):
    client = RecordingClient({"matched_key": AI_KEY, "source_keys": [AI_KEY], "answer": "5"})
    install_client(monkeypatch, client)
    chooser = builder(settings, STORE)
    decision = await chooser("Years of AI experience?", "text", [])
    assert decision.answer == "5"
    assert [call["model"] for call in client.calls] == ["provider/answers"]


async def test_store_override_works_without_general_model_even_with_context(settings, monkeypatch):
    settings.llm.model = None
    client = RecordingClient({"answer": "Yes", "source_keys": [AI_KEY]})
    install_client(monkeypatch, client)
    chooser = build_fill_chooser(settings, STORE, JobAnswerContext())
    assert chooser is not None
    decision = await chooser("Experience on AI?", "radio", ["Yes", "No"])
    assert decision.answer == "Yes"
    assert [call["model"] for call in client.calls] == ["provider/answers"]


async def test_context_wrapper_keeps_general_and_store_models_separate(settings, monkeypatch):
    context = JobAnswerContext(
        job_description=JobDescription(
            company="Acme", body="Acme builds reliable Python services."
        ),
        resume_text="Python engineer",
    )
    client = RecordingClient({"answer": "Yes", "source_keys": [AI_KEY]})
    install_client(monkeypatch, client)
    chooser = build_fill_chooser(settings, STORE, context)
    decision = await chooser("Experience on AI?", "radio", ["Yes", "No"])
    assert decision.answer == "Yes"
    client.reply = json.dumps({
        "job_specific": True, "answer": "I want to help Acme build reliable Python services.",
        "sources": ["job_description"], "evidence": [context.job_description.body],
    })
    decision = await chooser("Why do you want to work for Acme?", "textarea", [])
    assert decision.decided
    assert [call["model"] for call in client.calls] == ["provider/answers", "provider/general"]


async def test_failed_answer_override_returns_unknown_without_switching_models(
    settings, monkeypatch,
):
    client = RecordingClient({}, error=RuntimeError("model unavailable"))
    install_client(monkeypatch, client)
    chooser = build_fill_chooser(settings, STORE, None)
    decision = await chooser("Experience on AI?", "radio", ["Yes", "No"])
    assert not decision.decided
    assert [call["model"] for call in client.calls] == ["provider/answers"]


async def test_failed_resume_override_preserves_resume_error_without_switching(
    settings, monkeypatch,
):
    client = RecordingClient({}, error=RuntimeError("model unavailable"))
    install_client(monkeypatch, client)
    with pytest.raises(ResumeDescriptionError, match="model unavailable"):
        await pick_best_resume(
            JobDescription(title="Python"), [("r.txt", ResumeDescription(summary="Python"))],
            settings,
        )
    assert [call["model"] for call in client.calls] == ["provider/resumes"]


async def test_routed_derived_answer_reuses_cache_and_revalidates_sources(settings, monkeypatch):
    answers = dict(STORE)
    client = RecordingClient({"answer": "Yes", "source_keys": [AI_KEY]})
    install_client(monkeypatch, client)
    question = "Experience on AI?"
    chooser = build_reasoning_answer_chooser(settings, answers)
    assert (await chooser(question, "radio", ["Yes", "No"])).answer == "Yes"
    fresh = build_reasoning_answer_chooser(settings, answers)
    assert (await fresh(question, "radio", ["Yes", "No"])).answer == "Yes"
    assert len(client.calls) == 1
    answers[AI_KEY] = "0"
    client.reply = json.dumps({"answer": "No", "source_keys": [AI_KEY]})
    assert (await fresh(question, "radio", ["Yes", "No"])).answer == "No"
    assert [call["model"] for call in client.calls] == ["provider/answers"] * 2
    assert answers == {AI_KEY: "0"}
    assert not settings.answers_file.exists()


async def test_ungrounded_override_answer_remains_unknown(settings, monkeypatch):
    client = RecordingClient({"answer": "Yes", "source_keys": ["nonexistent"]})
    install_client(monkeypatch, client)
    chooser = build_fill_chooser(settings, STORE, None)
    assert not (await chooser("Experience on AI?", "radio", ["Yes", "No"])).decided


def test_startup_logs_each_resolved_model_without_credentials(settings, capsys):
    _log_models(settings)
    output = capsys.readouterr().out
    assert "task3=provider/resumes" in output
    assert "task10=provider/answers" in output
    assert "general=provider/general" in output
    assert "self-healing=" in output
    assert "test-secret" not in output
