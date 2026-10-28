"""Typed, validated configuration loaded from the environment.

The agent drives a browser (log in, search, select the Easy Apply filter, open a
job's Easy Apply form, read the job description), matches resumes offline, and
uses an LLM (Task 4.1/10) to answer questions from the store, so this exposes the
browser session settings, the LLM settings, the resumes folder, and the data
directory used for the persistent profile and debug screenshots. Variable names
follow the flat ``AUTOJOB_*`` scheme documented in ``.env.example``.
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
    # Task 2: how long to wait for a clicked job card to show up in the details
    # pane before retrying the click. A missed click can leave the pane on the
    # previous (already-applied) job, whose pane has no Easy Apply button.
    pane_switch_timeout_seconds: float = Field(default=6.0, gt=0)
    # Task 1: how long to keep looking for LinkedIn's optional "Try AI job
    # search" control after the results load. 0 skips the wait (the control is
    # optional, so an absent one must never stall the run).
    ai_search_timeout_seconds: float = Field(default=5.0, ge=0)
    # Slow-motion delay inserted between visible steps so a human can follow the
    # run. 0 disables it (the default); set it high for a watchable demo.
    step_delay_seconds: float = Field(default=0.0, ge=0)
    # Task 5: pause and ask the human (via a browser banner) when Task 4.1/10's LLM
    # cannot choose an answer for a question. Off means those questions are left
    # unanswered instead of prompting.
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
    # Task 4: when the walk stops at the terminal step (only **Submit
    # application** remains) the browser is left open for the human to review and
    # submit the application manually. The run waits for the human to close the
    # window, up to this many seconds; if it times out the browser is left open
    # anyway (the agent never closes it). 0 waits indefinitely.
    keep_open_timeout_seconds: float = Field(default=1800.0, ge=0)
    keep_open_poll_seconds: float = Field(default=1.0, gt=0)
    # Task 8: how many jobs one run may submit before the loop stops. 0 = keep
    # going until no unapplied job remains (or the human stops).
    max_jobs_per_run: int = Field(default=35, ge=0)

    @property
    def viewport(self) -> dict[str, int]:
        return {"width": self.viewport_width, "height": self.viewport_height}


class LLMSettings(BaseModel):
    """OpenRouter (OpenAI-compatible) text model used to answer form questions.

    Task 4.1/10 asks this model to classify each form question and answer it from
    the answer store (copying a stored answer or deriving one the stored entries
    entail). When it is not configured (no key or model),
    no answer is chosen and every question is handed to Task 5 instead.
    """

    api_key: str | None = None
    base_url: str = "https://openrouter.ai/api/v1"
    model: str | None = None
    temperature: float = Field(default=0.0, ge=0, le=2)
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    # Task 3.2: reasoning models can spend thousands of tokens "thinking" before a
    # two-line JSON answer. On OpenRouter the structured description/match calls
    # disable that hidden reasoning by default (much faster, and no empty reply
    # when the reasoning fills the output budget).
    disable_reasoning: bool = True

    @property
    def configured(self) -> bool:
        """True when a key and a model are present, so a request can be made."""
        return bool(self.api_key and self.model)


class SelfHealingSettings(BaseModel):
    """Task 11: bounded recovery when the Easy Apply form changes or crashes.

    ``repair_command`` is optional and opt-in. It runs **after** the failed browser
    is closed, with ``AUTOJOB_FAILURE_BUNDLE`` and ``AUTOJOB_BUG_ID`` in its
    environment; ``test_command`` then guards reopening. With neither configured,
    the loop only restarts the browser and retries the same job.
    """

    enabled: bool = True
    max_repair_attempts: int = Field(default=3, ge=0, le=10)
    repair_command: str | None = None
    test_command: str | None = None
    command_timeout_seconds: float = Field(default=900.0, gt=0)
    close_timeout_seconds: float = Field(default=20.0, gt=0)


class Settings(BaseModel):
    """Root settings object."""

    session: SessionSettings = Field(default_factory=SessionSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    self_healing: SelfHealingSettings = Field(default_factory=SelfHealingSettings)
    data_dir: Path = PROJECT_ROOT / "data"
    resumes_dir: Path = PROJECT_ROOT / "resumes"
    answers_path: Path | None = None
    # Task 10.3: cached answers the LLM derived from the store (kept apart from
    # the human-confirmed answers.json).
    derived_answers_path: Path | None = None
    resume_library_path: Path | None = None
    # Task 3.2: the LLM-written profile for each resume, keyed by its canonical
    # path (see src/tools/resume_descriptions/).
    resume_descriptions_path: Path | None = None

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

    @property
    def derived_answers_file(self) -> Path:
        """Task 10.3 cache of answers the LLM derived from the store."""
        return self.derived_answers_path or (self.data_dir / "derived_answers.json")

    @property
    def resume_library_file(self) -> Path:
        """Job profile → human-provided resume store used by Task 3.1."""
        return self.resume_library_path or (self.data_dir / "resume_library.json")

    @property
    def resume_descriptions_file(self) -> Path:
        """Resume path → LLM-written description store used by Task 3.2."""
        return self.resume_descriptions_path or (self.data_dir / "resume_descriptions.json")


def load_settings(env_file: Path | None = None) -> Settings:
    """Read settings from ``.env`` and the process environment."""
    _load_env_file(env_file)
    data_dir = _get_str("AUTOJOB_DATA_DIR")
    resumes_dir = _get_str("AUTOJOB_RESUMES_DIR")
    answers_path = _get_str("AUTOJOB_ANSWERS_FILE")
    derived_answers_path = _get_str("AUTOJOB_DERIVED_ANSWERS_FILE")
    resume_library_path = _get_str("AUTOJOB_RESUME_LIBRARY")
    resume_descriptions_path = _get_str("AUTOJOB_RESUME_DESCRIPTIONS")
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
            pane_switch_timeout_seconds=_get_float(
                "AUTOJOB_SESSION_PANE_SWITCH_TIMEOUT_SECONDS", 6.0
            ),
            ai_search_timeout_seconds=_get_float(
                "AUTOJOB_SESSION_AI_SEARCH_TIMEOUT_SECONDS", 5.0
            ),
            step_delay_seconds=_get_float("AUTOJOB_SESSION_STEP_DELAY_SECONDS", 0.0),
            ask_human=_get_bool("AUTOJOB_SESSION_ASK_HUMAN", True),
            ask_timeout_seconds=_get_float("AUTOJOB_SESSION_ASK_TIMEOUT_SECONDS", 300.0),
            ask_poll_seconds=_get_float("AUTOJOB_SESSION_ASK_POLL_SECONDS", 1.0),
            clean_stale_profile=_get_bool("AUTOJOB_SESSION_CLEAN_STALE_PROFILE", True),
            skip_applied=_get_bool("AUTOJOB_SESSION_SKIP_APPLIED", True),
            keep_open_timeout_seconds=_get_float(
                "AUTOJOB_SESSION_KEEP_OPEN_TIMEOUT_SECONDS", 1800.0
            ),
            keep_open_poll_seconds=_get_float("AUTOJOB_SESSION_KEEP_OPEN_POLL_SECONDS", 1.0),
            max_jobs_per_run=_get_int("AUTOJOB_SESSION_MAX_JOBS", 35),
        ),
        llm=LLMSettings(
            api_key=_get_str("OPENROUTER_API_KEY") or _get_str("AUTOJOB_LLM_API_KEY"),
            base_url=_get_str("AUTOJOB_LLM_BASE_URL", "https://openrouter.ai/api/v1"),
            model=_get_str("AUTOJOB_LLM_MODEL"),
            temperature=_get_float("AUTOJOB_LLM_TEMPERATURE", 0.0),
            timeout_seconds=_get_float("AUTOJOB_LLM_TIMEOUT_SECONDS", 60.0),
            max_retries=_get_int("AUTOJOB_LLM_MAX_RETRIES", 3),
            disable_reasoning=_get_bool("AUTOJOB_LLM_DISABLE_REASONING", True),
        ),
        self_healing=SelfHealingSettings(
            enabled=_get_bool("AUTOJOB_SELF_HEAL_ENABLED", True),
            max_repair_attempts=_get_int("AUTOJOB_SELF_HEAL_MAX_ATTEMPTS", 3),
            repair_command=_get_str("AUTOJOB_SELF_HEAL_REPAIR_COMMAND"),
            test_command=_get_str("AUTOJOB_SELF_HEAL_TEST_COMMAND"),
            command_timeout_seconds=_get_float(
                "AUTOJOB_SELF_HEAL_COMMAND_TIMEOUT_SECONDS", 900.0
            ),
            close_timeout_seconds=_get_float("AUTOJOB_SELF_HEAL_CLOSE_TIMEOUT_SECONDS", 20.0),
        ),
        data_dir=Path(data_dir).expanduser() if data_dir else PROJECT_ROOT / "data",
        resumes_dir=(Path(resumes_dir).expanduser() if resumes_dir else PROJECT_ROOT / "resumes"),
        answers_path=Path(answers_path).expanduser() if answers_path else None,
        derived_answers_path=(
            Path(derived_answers_path).expanduser() if derived_answers_path else None
        ),
        resume_library_path=(
            Path(resume_library_path).expanduser() if resume_library_path else None
        ),
        resume_descriptions_path=(
            Path(resume_descriptions_path).expanduser() if resume_descriptions_path else None
        ),
    )
