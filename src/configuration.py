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
    # Slow-motion delay inserted between visible steps so a human can follow the
    # run. 0 disables it (the default); set it high for a watchable demo.
    step_delay_seconds: float = Field(default=0.0, ge=0)

    @property
    def viewport(self) -> dict[str, int]:
        return {"width": self.viewport_width, "height": self.viewport_height}


class Settings(BaseModel):
    """Root settings object."""

    session: SessionSettings = Field(default_factory=SessionSettings)
    data_dir: Path = PROJECT_ROOT / "data"
    resumes_dir: Path = PROJECT_ROOT / "resumes"
    answers_path: Path | None = None

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
            step_delay_seconds=_get_float("AUTOJOB_SESSION_STEP_DELAY_SECONDS", 0.0),
        ),
        data_dir=Path(data_dir).expanduser() if data_dir else PROJECT_ROOT / "data",
        resumes_dir=(Path(resumes_dir).expanduser() if resumes_dir else PROJECT_ROOT / "resumes"),
        answers_path=Path(answers_path).expanduser() if answers_path else None,
    )
