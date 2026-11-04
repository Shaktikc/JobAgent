"""Independent Task 3/10 model overrides and their general-model defaults."""

from __future__ import annotations

import os

import pytest

from src.configuration import DEFAULT_REPAIR_MODEL, LLMSettings, Settings, load_settings
from src.llm_model_routing import answer_llm_settings, resume_llm_settings


@pytest.fixture
def configured_env(monkeypatch):
    for name in list(os.environ):
        if name.startswith("AUTOJOB_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("AUTOJOB_LLM_MODEL", "provider/general")


def test_task_models_are_loaded_and_resolved_independently(configured_env, monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOJOB_RESUME_LLM_MODEL", '  "provider/resumes"  ')
    monkeypatch.setenv("AUTOJOB_ANSWERS_LLM_MODEL", "provider/answers")
    settings = load_settings(tmp_path / "missing.env")

    assert resume_llm_settings(settings).model == "provider/resumes"
    assert answer_llm_settings(settings).model == "provider/answers"
    assert settings.llm.model == "provider/general"
    assert settings.self_healing.repair_model == DEFAULT_REPAIR_MODEL

    monkeypatch.setenv("AUTOJOB_RESUME_LLM_MODEL", "provider/new-resumes")
    changed = load_settings(tmp_path / "missing.env")
    assert resume_llm_settings(changed).model == "provider/new-resumes"
    assert answer_llm_settings(changed).model == "provider/answers"

    monkeypatch.setenv("AUTOJOB_ANSWERS_LLM_MODEL", "provider/new-answers")
    changed = load_settings(tmp_path / "missing.env")
    assert answer_llm_settings(changed).model == "provider/new-answers"
    assert resume_llm_settings(changed).model == "provider/new-resumes"
    assert changed.llm.model == "provider/general"
    assert changed.self_healing.repair_model == DEFAULT_REPAIR_MODEL


@pytest.mark.parametrize("override", [None, "", "  ", ' "" ', " '' "])
def test_unset_or_blank_overrides_use_general_not_the_other_task(
    configured_env, monkeypatch, tmp_path, override
):
    if override is not None:
        monkeypatch.setenv("AUTOJOB_RESUME_LLM_MODEL", override)
    monkeypatch.setenv("AUTOJOB_ANSWERS_LLM_MODEL", "provider/answers")
    settings = load_settings(tmp_path / "missing.env")
    assert resume_llm_settings(settings).model == "provider/general"
    assert answer_llm_settings(settings).model == "provider/answers"

    monkeypatch.setenv("AUTOJOB_RESUME_LLM_MODEL", "provider/resumes")
    if override is None:
        monkeypatch.delenv("AUTOJOB_ANSWERS_LLM_MODEL")
    else:
        monkeypatch.setenv("AUTOJOB_ANSWERS_LLM_MODEL", override)
    settings = load_settings(tmp_path / "missing.env")
    assert answer_llm_settings(settings).model == "provider/general"
    assert resume_llm_settings(settings).model == "provider/resumes"


def test_overrides_work_without_a_general_model(configured_env, monkeypatch, tmp_path):
    monkeypatch.delenv("AUTOJOB_LLM_MODEL")
    monkeypatch.setenv("AUTOJOB_RESUME_LLM_MODEL", "provider/resumes")
    settings = load_settings(tmp_path / "missing.env")
    assert resume_llm_settings(settings).configured
    assert not answer_llm_settings(settings).configured
    assert not settings.llm.configured


def test_resolving_models_preserves_connection_settings_and_does_not_mutate_general():
    llm = LLMSettings(
        api_key="test-key", model="general", resume_model="resumes", answers_model="answers",
        base_url="https://example.test/v1", temperature=0.4, timeout_seconds=12,
        max_retries=1, transport_retries=4, transport_retry_backoff_seconds=0.25,
        disable_reasoning=False,
    )
    settings = Settings(llm=llm)
    for resolve, model in [(resume_llm_settings, "resumes"), (answer_llm_settings, "answers")]:
        resolved = resolve(settings)
        assert resolved.model == model
        assert resolved.model_dump(exclude={"model"}) == llm.model_dump(exclude={"model"})
        resolved.model = "changed-copy"
        assert llm.model == "general"


def test_override_without_credentials_is_not_configured():
    settings = Settings(llm=LLMSettings(resume_model="resumes", answers_model="answers"))
    assert not resume_llm_settings(settings).configured
    assert not answer_llm_settings(settings).configured
