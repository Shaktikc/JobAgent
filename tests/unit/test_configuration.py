"""Unit tests for configuration schemas and loaders (Task 1).

No network, no browser: these exercise pure parsing and env handling.
"""

from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest

from src.configuration import (
    REPO_ROOT,
    FactsConfig,
    GuardSettings,
    LLMSettings,
    Paths,
    ResumeRoutingConfig,
    SearchConfig,
    load_yaml,
)

CONFIG_DIR = REPO_ROOT / "config"

GUARD_ENV_KEYS = (
    "AUTOJOB_GUARD_DAILY_CAP",
    "AUTOJOB_GUARD_HOURS_START",
    "AUTOJOB_GUARD_HOURS_END",
    "AUTOJOB_GUARD_MIN_DELAY_SECONDS",
    "AUTOJOB_GUARD_MAX_DELAY_SECONDS",
)


def _clear(monkeypatch: pytest.MonkeyPatch, keys: tuple[str, ...]) -> None:
    for key in keys:
        monkeypatch.delenv(key, raising=False)


# --- Paths -----------------------------------------------------------------


def test_ensure_runtime_dirs_creates_data_tree(tmp_path: Path) -> None:
    paths = Paths(
        root=tmp_path,
        config=tmp_path / "config",
        resumes=tmp_path / "resumes",
        data=tmp_path / "data",
        db=tmp_path / "data" / "autojobapply.db",
        profile=tmp_path / "data" / "profile",
        artifacts=tmp_path / "data" / "artifacts",
        stop=tmp_path / "data" / "STOP",
    )

    paths.ensure_runtime_dirs()

    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "data" / "profile").is_dir()
    assert (tmp_path / "data" / "artifacts").is_dir()


# --- Guard -----------------------------------------------------------------


def test_guard_defaults_match_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch, GUARD_ENV_KEYS)

    guard = GuardSettings.from_env()

    assert guard.daily_cap == 30
    assert guard.hours_start == time(9, 0)
    assert guard.hours_end == time(18, 0)
    assert guard.min_delay_seconds == 20
    assert guard.max_delay_seconds == 90


def test_guard_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch, GUARD_ENV_KEYS)
    monkeypatch.setenv("AUTOJOB_GUARD_DAILY_CAP", "7")
    monkeypatch.setenv("AUTOJOB_GUARD_HOURS_START", "08:30")

    guard = GuardSettings.from_env()

    assert guard.daily_cap == 7
    assert guard.hours_start == time(8, 30)


# --- LLM -------------------------------------------------------------------


def test_llm_env_is_read_and_base_url_defaults_to_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("AUTOJOB_LLM_MODEL", "vendor/model-a")

    llm = LLMSettings.from_env()

    assert llm.api_key == "sk-test"
    assert llm.model == "vendor/model-a"
    assert llm.base_url == "https://openrouter.ai/api/v1"


def test_llm_model_is_not_hardcoded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOJOB_LLM_MODEL", "vendor/model-b")
    assert LLMSettings.from_env().model == "vendor/model-b"


# --- YAML loaders ----------------------------------------------------------


def test_load_yaml_rejects_non_mapping(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")

    with pytest.raises(ValueError):
        load_yaml(path)


def test_shipped_search_template_parses() -> None:
    cfg = SearchConfig.from_yaml(CONFIG_DIR / "search.yaml")

    assert cfg.keywords
    assert cfg.easy_apply_only is True
    assert cfg.exclude_keywords


def test_shipped_facts_template_parses() -> None:
    cfg = FactsConfig.from_yaml(CONFIG_DIR / "facts.yaml")

    assert cfg.rules
    assert "work_authorization" in cfg.facts


def test_shipped_resumes_template_allows_no_default_variant() -> None:
    cfg = ResumeRoutingConfig.from_yaml(CONFIG_DIR / "resumes.yaml")

    assert cfg.default_variant is None
    assert cfg.overrides == []


def test_resume_routing_missing_file_returns_defaults(tmp_path: Path) -> None:
    cfg = ResumeRoutingConfig.from_yaml(tmp_path / "does-not-exist.yaml")

    assert cfg.default_variant is None
    assert cfg.reindex is False
