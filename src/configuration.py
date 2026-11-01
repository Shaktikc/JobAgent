"""Typed, validated configuration loaded from the environment.

The agent drives a browser (log in, search, select the Easy Apply filter, open a
job's Easy Apply form, read the job description), matches resumes offline, and
uses an LLM (Task 4.1/10) to answer questions from the store, so this exposes the
browser session settings, the LLM settings, the self-healing repair model, the
resumes folder, and the data directory used for the persistent profile and debug
screenshots. The general-purpose model (``AUTOJOB_LLM_MODEL``) and the
self-healing model (``AUTOJOB_SELF_HEAL_REPAIR_MODEL``) are configured
independently; there is no cross-purpose fallback. Variable names follow the flat
``AUTOJOB_*`` scheme documented in ``.env.example``.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

# Task 14: the self-healing repair agent has its own model, independent of the
# general-purpose model in ``AUTOJOB_LLM_MODEL``. The Python app talks to
# OpenRouter with bare ids; the repair wrapper adds the OpenCode provider prefix
# (``openrouter/deepseek/...``) when it launches the CLI.
DEFAULT_REPAIR_MODEL = "deepseek/deepseek-v4.1-flash-1017"
OPENCODE_PROVIDER = "openrouter"


def clean_model_id(value: str | None) -> str:
    """Strip surrounding whitespace and quotes from a configured model id."""
    return (value or "").strip().strip('"').strip("'").strip()


def opencode_model_id(model_id: str | None) -> str:
    """Return the OpenCode CLI id for an OpenRouter model id.

    ``deepseek/deepseek-v4.1-flash-1017`` becomes
    ``openrouter/deepseek/deepseek-v4.1-flash-1017``. An id that already names
    the ``openrouter`` provider is returned unchanged.
    """
    value = clean_model_id(model_id)
    if not value:
        return ""
    if value.startswith(f"{OPENCODE_PROVIDER}/"):
        return value
    return f"{OPENCODE_PROVIDER}/{value}"


def resolve_repair_model(explicit: str | None = None) -> str:
    """Resolve the self-healing model to the OpenCode CLI id.

    An explicit override is used verbatim so another provider can be selected;
    only the bare DeepSeek default is normalized to OpenCode's
    ``openrouter/...`` form. The general-purpose model in
    ``AUTOJOB_LLM_MODEL`` is never consulted: changing it must not change the
    repair model, and vice versa.
    """
    value = clean_model_id(explicit)
    if value and value != DEFAULT_REPAIR_MODEL:
        return value
    return opencode_model_id(DEFAULT_REPAIR_MODEL)


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


def _get_model(name: str, default: str) -> str:
    """Read a model id, stripping whitespace/quotes and falling back to ``default``."""
    return clean_model_id(os.environ.get(name)) or default


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
    # Task 16: apply when the LLM rates an existing resume partial or strong
    # for the job. With no eligible match the job is skipped (the human is not asked
    # for a resume and the remembered-resume fallback is not used). Set false to
    # restore Task 3.1's fallbacks.
    require_resume_match: bool = True
    # Task 16: optional safety cap on jobs skipped for having no matching resume;
    # 0 (the default) = no cap. A skip never counts toward ``max_jobs_per_run``.
    max_skipped_jobs_per_run: int = Field(default=0, ge=0)
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
    """General-purpose OpenRouter (OpenAI-compatible) text model.

    Every non-healing LLM path uses ``model`` (``AUTOJOB_LLM_MODEL``): resume
    descriptions and best-resume matching (Task 3.2), form answers (Task 4.1/10),
    and job-context answers (Task 12). When it is not configured (no key or
    model), no answer is chosen and every question is handed to Task 5 instead.
    The self-healing repair agent has its own model and never uses this one.
    """

    api_key: str | None = None
    base_url: str = "https://openrouter.ai/api/v1"
    model: str | None = None
    temperature: float = Field(default=0.0, ge=0, le=2)
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    # Task 3.2: the OpenAI client retries some failures itself, but a provider-side
    # "Connection error." (or a 429/5xx) can still escape and abort a resume match.
    # Retry those transient transport failures a bounded number of times with a
    # short exponential backoff before recording the Task 3 error. Deterministic
    # failures (bad request, unusable reply) are never retried here.
    transport_retries: int = Field(default=2, ge=0, le=5)
    transport_retry_backoff_seconds: float = Field(default=1.0, ge=0)
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
    is closed, with ``AUTOJOB_FAILURE_BUNDLE``, ``AUTOJOB_BUG_ID``, and the
    configured ``repair_model`` in its environment; ``test_command`` then guards
    reopening. With neither configured, the loop only restarts the browser and
    retries the same job.

    ``repair_model`` (``AUTOJOB_SELF_HEAL_REPAIR_MODEL``) is the **self-healing**
    model, independent of the general-purpose ``llm.model``. It defaults to
    DeepSeek V4.1 Flash 1017 for reasoning over code, evidence, and tests; the
    repair wrapper maps the bare OpenRouter id to OpenCode's
    ``openrouter/deepseek/...`` form.
    """

    enabled: bool = True
    max_repair_attempts: int = Field(default=3, ge=0, le=10)
    repair_model: str = DEFAULT_REPAIR_MODEL
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
    # Task 15: explicit intake-folder override. When unset, the intake folder is
    # ``<resumes_dir>/new`` (see :attr:`new_resumes_dir`).
    new_resumes_path: Path | None = None
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
    def new_resumes_dir(self) -> Path:
        """Task 15: intake folder for resumes described before they join the pool.

        Defaults to ``<resumes_dir>/new`` so the intake folder moves files into
        the existing resume pool. An explicit ``AUTOJOB_NEW_RESUMES_DIR`` wins.
        """
        return self.new_resumes_path or (self.resumes_dir / "new")

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
    new_resumes_path = _get_str("AUTOJOB_NEW_RESUMES_DIR")
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
            require_resume_match=_get_bool("AUTOJOB_SESSION_REQUIRE_RESUME_MATCH", True),
            max_skipped_jobs_per_run=_get_int("AUTOJOB_SESSION_MAX_SKIPPED_JOBS", 0),
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
            transport_retries=_get_int("AUTOJOB_LLM_TRANSPORT_RETRIES", 2),
            transport_retry_backoff_seconds=_get_float(
                "AUTOJOB_LLM_TRANSPORT_RETRY_BACKOFF_SECONDS", 1.0
            ),
            disable_reasoning=_get_bool("AUTOJOB_LLM_DISABLE_REASONING", True),
        ),
        self_healing=SelfHealingSettings(
            enabled=_get_bool("AUTOJOB_SELF_HEAL_ENABLED", True),
            max_repair_attempts=_get_int("AUTOJOB_SELF_HEAL_MAX_ATTEMPTS", 3),
            repair_model=_get_model(
                "AUTOJOB_SELF_HEAL_REPAIR_MODEL", DEFAULT_REPAIR_MODEL
            ),
            repair_command=_get_str("AUTOJOB_SELF_HEAL_REPAIR_COMMAND"),
            test_command=_get_str("AUTOJOB_SELF_HEAL_TEST_COMMAND"),
            command_timeout_seconds=_get_float(
                "AUTOJOB_SELF_HEAL_COMMAND_TIMEOUT_SECONDS", 900.0
            ),
            close_timeout_seconds=_get_float("AUTOJOB_SELF_HEAL_CLOSE_TIMEOUT_SECONDS", 20.0),
        ),
        data_dir=Path(data_dir).expanduser() if data_dir else PROJECT_ROOT / "data",
        resumes_dir=(Path(resumes_dir).expanduser() if resumes_dir else PROJECT_ROOT / "resumes"),
        new_resumes_path=(
            Path(new_resumes_path).expanduser() if new_resumes_path else None
        ),
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
