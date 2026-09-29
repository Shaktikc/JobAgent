"""Configuration schemas and loaders for AutoJobApply.

Single source of settings for the whole application. Graph nodes receive config
explicitly and never read environment variables directly (SPEC.md §5).

Only shapes and loading live here. Behaviour (rule matching, routing, searching)
lives in the corresponding nodes.
"""

from __future__ import annotations

import os
from datetime import time
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def load_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML file into a mapping. Raises FileNotFoundError if missing."""
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return data


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------


class Paths(BaseModel):
    """Filesystem locations. Runtime state lives under `data/` and is gitignored."""

    root: Path = REPO_ROOT
    config: Path = REPO_ROOT / "config"
    resumes: Path = REPO_ROOT / "resumes"
    data: Path = REPO_ROOT / "data"
    db: Path = REPO_ROOT / "data" / "autojobapply.db"
    profile: Path = REPO_ROOT / "data" / "profile"
    artifacts: Path = REPO_ROOT / "data" / "artifacts"
    stop: Path = REPO_ROOT / "data" / "STOP"

    def ensure_runtime_dirs(self) -> None:
        for directory in (self.data, self.artifacts, self.profile):
            directory.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# LLM (OpenRouter — model is swappable by env var, no code change)
# --------------------------------------------------------------------------


class LLMSettings(BaseModel):
    api_key: str | None = None
    model: str | None = None
    base_url: str = OPENROUTER_BASE_URL
    temperature: float = 0.0
    timeout_seconds: int = 60
    max_retries: int = 3

    @classmethod
    def from_env(cls) -> LLMSettings:
        return cls(
            api_key=os.environ.get("OPENROUTER_API_KEY") or None,
            model=os.environ.get("AUTOJOB_LLM_MODEL") or None,
            base_url=os.environ.get("AUTOJOB_LLM_BASE_URL") or OPENROUTER_BASE_URL,
            temperature=float(os.environ.get("AUTOJOB_LLM_TEMPERATURE", "0")),
            timeout_seconds=int(os.environ.get("AUTOJOB_LLM_TIMEOUT_SECONDS", "60")),
            max_retries=int(os.environ.get("AUTOJOB_LLM_MAX_RETRIES", "3")),
        )


# --------------------------------------------------------------------------
# Guard (pacing, daily cap, business hours)
# --------------------------------------------------------------------------


class GuardSettings(BaseModel):
    """Safety envelope. Values confirmed in SPEC.md §7; changing them needs approval."""

    daily_cap: int = 30
    hours_start: time = time(9, 0)
    hours_end: time = time(18, 0)
    min_delay_seconds: int = 20
    max_delay_seconds: int = 90

    @classmethod
    def from_env(cls) -> GuardSettings:
        return cls(
            daily_cap=int(os.environ.get("AUTOJOB_GUARD_DAILY_CAP", "30")),
            hours_start=time.fromisoformat(os.environ.get("AUTOJOB_GUARD_HOURS_START", "09:00")),
            hours_end=time.fromisoformat(os.environ.get("AUTOJOB_GUARD_HOURS_END", "18:00")),
            min_delay_seconds=int(os.environ.get("AUTOJOB_GUARD_MIN_DELAY_SECONDS", "20")),
            max_delay_seconds=int(os.environ.get("AUTOJOB_GUARD_MAX_DELAY_SECONDS", "90")),
        )


# --------------------------------------------------------------------------
# config/search.yaml
# --------------------------------------------------------------------------


class SearchConfig(BaseModel):
    """Search criteria. Filtering is keyword-based only (SPEC.md §7)."""

    keywords: list[str] = Field(min_length=1)
    location: str = ""
    remote: bool = False
    easy_apply_only: bool = True
    posted_within_days: int = 3
    experience_levels: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    exclude_companies: list[str] = Field(default_factory=list)
    max_results_per_run: int = 40

    @classmethod
    def from_yaml(cls, path: Path) -> SearchConfig:
        return cls.model_validate(load_yaml(path))


# --------------------------------------------------------------------------
# config/resumes.yaml (optional overrides; resumes are auto-indexed)
# --------------------------------------------------------------------------


class ResumeVariant(BaseModel):
    """A resume plus the role keywords used to match it to a job.

    Keywords are normally LLM-extracted from the PDF and cached; this model is
    the in-memory representation either way.
    """

    file: Path
    role_keywords: list[str] = Field(default_factory=list)
    extracted: bool = False


class ResumeRoutingConfig(BaseModel):
    """Optional overrides. Absent file means: rely on auto-indexing entirely."""

    overrides: list[ResumeVariant] = Field(default_factory=list)
    default_variant: Path | None = None
    reindex: bool = False

    @classmethod
    def from_yaml(cls, path: Path) -> ResumeRoutingConfig:
        if not path.exists():
            return cls()
        return cls.model_validate(load_yaml(path))


# --------------------------------------------------------------------------
# config/facts.yaml
# --------------------------------------------------------------------------


class FactsRule(BaseModel):
    """A hard rule. Rules always take precedence over the LLM (SPEC.md §7)."""

    match: str
    answer: str | None = None
    answer_from: str | None = None


class FactsConfig(BaseModel):
    facts: dict[str, Any] = Field(default_factory=dict)
    rules: list[FactsRule] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path) -> FactsConfig:
        return cls.model_validate(load_yaml(path))


# --------------------------------------------------------------------------
# Aggregate
# --------------------------------------------------------------------------


class AppSettings(BaseModel):
    paths: Paths = Field(default_factory=Paths)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    guard: GuardSettings = Field(default_factory=GuardSettings)

    @classmethod
    def from_env(cls) -> AppSettings:
        return cls(
            paths=Paths(),
            llm=LLMSettings.from_env(),
            guard=GuardSettings.from_env(),
        )
