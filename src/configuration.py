"""Typed, validated configuration loaded from the environment.

The agent drives a browser (log in, search, select the Easy Apply filter, open a
job's Easy Apply form, read the job description) and then matches resumes
offline, so this exposes the browser session settings, the resumes folder, and
the data directory used for the persistent profile and debug screenshots.
Variable names follow the flat ``AUTOJOB_*`` scheme documented in
``.env.example``.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


def _load_env_file(env_file: Path | None) -> None:
    """Load ``.env`` without clobbering variables already set in the shell."""
    path = env_file or DEFAULT_ENV_FILE
    if path.is_file():
        load_dotenv(path, override=False)


def _get_str(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _get_int(name: str, default: int) -> int:
    raw = _get_str(name)
    return default if raw is None else int(raw)


def _get_float(name: str, default: float) -> float:
    raw = _get_str(name)
    return default if raw is None else float(raw)


def _get_bool(name: str, default: bool) -> bool:
    raw = _get_str(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


class SessionSettings(BaseModel):
    """Browser identity, timeouts, and the human login gate."""

    headless: bool = False
    viewport_width: int = Field(default=1280, gt=0)
    viewport_height: int = Field(default=800, gt=0)
    user_agent: str | None = None
    navigation_timeout_ms: int = Field(default=60_000, gt=0)
    # How long to wait for the user to finish logging in, and how often to poll.
    login_timeout_seconds: int = Field(default=300, gt=0)
    login_poll_seconds: float = Field(default=2.0, gt=0)
    # Settle time after clicking the Easy Apply filter before verifying it.
    post_click_wait_seconds: float = Field(default=2.0, ge=0)
    # How long to wait for the job details apply button and then the Easy Apply
    # application form to appear.
    easy_apply_timeout_seconds: float = Field(default=20.0, gt=0)
    # Task 1: how long to keep looking for LinkedIn's optional "Try AI job
    # search" control after the results load. 0 skips the wait (the control is
    # optional, so an absent one must never stall the run).
    ai_search_timeout_seconds: float = Field(default=5.0, ge=0)
    # Slow-motion delay inserted between visible steps so a human can follow the
    # run. 0 disables it (the default); set it high for a watchable demo.
    step_delay_seconds: float = Field(default=0.0, ge=0)
    # Task 5: pause and ask the human (via a browser banner) when the form asks a
    # question the answer store cannot answer. Off means unknown questions are
    # just left for a later run.
    ask_human: bool = True
    ask_timeout_seconds: float = Field(default=300.0, gt=0)
    ask_poll_seconds: float = Field(default=1.0, gt=0)
    # Before launching, recover a profile lock left by a crashed/interrupted run
    # by clearing its stale lock files. A lock held by a live browser is never
    # force-killed (that dropped another run's CDP link); the launch stops with a
    # clear error instead. Use `autojob --clean-profile` to force-close browsers.
    clean_stale_profile: bool = True
    # Task 6: skip job cards whose status is already "Applied" and open the next
    # unapplied job instead. Set false to ignore the Applied status (open the
    # first Easy Apply card regardless).
    skip_applied: bool = True
    # Task 4 steps 2-3: use browser-use's LLM agent to decide which form fields
    # already have a known answer (from the answer store) and fill them. Requires
    # a configured LLM (see LlmSettings / AUTOJOB_LLM_MODEL) and an OpenRouter API
    # key; without those it is a no-op and the deterministic fill runs instead.
    # Set false to always use the deterministic fill.
    agent_fill: bool = True

    @property
    def viewport(self) -> dict[str, int]:
        return {"width": self.viewport_width, "height": self.viewport_height}


class LlmSettings(BaseModel):
    """The OpenRouter model that drives Task 4's browser-use agent (steps 2-3).

    An empty ``model`` disables the agent, keeping the offline deterministic fill
    the default. The API key is read from ``OPENROUTER_API_KEY`` (never stored
    here) so it cannot leak into the run state or logs.
    """

    model: str = ""
    temperature: float = Field(default=0.0, ge=0.0)
    # Overall seconds budget for one form step's agent run.
    timeout_seconds: float = Field(default=180.0, gt=0)
    # Safety cap on how many agent steps one form step may take.
    max_steps: int = Field(default=20, gt=0)

    @property
    def configured(self) -> bool:
        """True when a model id is set (the agent can be built)."""
        return bool(self.model.strip())


class Settings(BaseModel):
    """Root settings object."""

    session: SessionSettings = Field(default_factory=SessionSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    data_dir: Path = PROJECT_ROOT / "data"
    resumes_dir: Path = PROJECT_ROOT / "resumes"
    answers_path: Path | None = None

    @property
    def agent_fill_enabled(self) -> bool:
        """True when Task 4's LLM agent should drive steps 2-3.

        Requires the feature gate, a configured model, and an OpenRouter API key
        in the environment; otherwise the deterministic fill is used.
        """
        return (
            self.session.agent_fill
            and self.llm.configured
            and bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
        )

    @property
    def profile_dir(self) -> Path:
        """Persistent Chromium profile directory (cookies, logins)."""
        return self.data_dir / "profile"

    @property
    def debug_dir(self) -> Path:
        """Where failure screenshots are written."""
        return self.data_dir / "debug"

    @property
    def answers_file(self) -> Path:
        """Question → answer store used by Tasks 4-5."""
        return self.answers_path or (self.data_dir / "answers.json")


def load_settings(env_file: Path | None = None) -> Settings:
    """Read settings from ``.env`` and the process environment."""
    _load_env_file(env_file)
    data_dir = _get_str("AUTOJOB_DATA_DIR")
    resumes_dir = _get_str("AUTOJOB_RESUMES_DIR")
    answers_path = _get_str("AUTOJOB_ANSWERS_FILE")
    return Settings(
        session=SessionSettings(
            headless=_get_bool("AUTOJOB_SESSION_HEADLESS", False),
            viewport_width=_get_int("AUTOJOB_SESSION_VIEWPORT_WIDTH", 1280),
            viewport_height=_get_int("AUTOJOB_SESSION_VIEWPORT_HEIGHT", 800),
            user_agent=_get_str("AUTOJOB_SESSION_USER_AGENT"),
            navigation_timeout_ms=_get_int("AUTOJOB_SESSION_NAVIGATION_TIMEOUT_MS", 60_000),
            login_timeout_seconds=_get_int("AUTOJOB_SESSION_LOGIN_TIMEOUT_SECONDS", 300),
            login_poll_seconds=_get_float("AUTOJOB_SESSION_LOGIN_POLL_SECONDS", 2.0),
            post_click_wait_seconds=_get_float("AUTOJOB_SESSION_POST_CLICK_WAIT_SECONDS", 2.0),
            easy_apply_timeout_seconds=_get_float(
                "AUTOJOB_SESSION_EASY_APPLY_TIMEOUT_SECONDS", 20.0
            ),
            ai_search_timeout_seconds=_get_float("AUTOJOB_SESSION_AI_SEARCH_TIMEOUT_SECONDS", 5.0),
            step_delay_seconds=_get_float("AUTOJOB_SESSION_STEP_DELAY_SECONDS", 0.0),
            ask_human=_get_bool("AUTOJOB_SESSION_ASK_HUMAN", True),
            ask_timeout_seconds=_get_float("AUTOJOB_SESSION_ASK_TIMEOUT_SECONDS", 300.0),
            ask_poll_seconds=_get_float("AUTOJOB_SESSION_ASK_POLL_SECONDS", 1.0),
            clean_stale_profile=_get_bool("AUTOJOB_SESSION_CLEAN_STALE_PROFILE", True),
            skip_applied=_get_bool("AUTOJOB_SESSION_SKIP_APPLIED", True),
            agent_fill=_get_bool("AUTOJOB_SESSION_AGENT_FILL", True),
        ),
        llm=LlmSettings(
            model=_get_str("AUTOJOB_LLM_MODEL", "") or "",
            temperature=_get_float("AUTOJOB_LLM_TEMPERATURE", 0.0),
            timeout_seconds=_get_float("AUTOJOB_LLM_TIMEOUT_SECONDS", 180.0),
            max_steps=_get_int("AUTOJOB_LLM_MAX_STEPS", 20),
        ),
        data_dir=Path(data_dir).expanduser() if data_dir else PROJECT_ROOT / "data",
        resumes_dir=(Path(resumes_dir).expanduser() if resumes_dir else PROJECT_ROOT / "resumes"),
        answers_path=Path(answers_path).expanduser() if answers_path else None,
    )
