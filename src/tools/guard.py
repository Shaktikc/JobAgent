"""`guard` — pacing, daily cap, business hours, and the STOP sentinel.

Implemented in Task 4. Every network or browser action must pass through here
(SPEC.md §8). Values come from ``configuration.GuardSettings``; changing them is an
"ask first" action. Clock and sleep are injectable so tests are instant.

Also halts immediately on a LinkedIn rate-limit or checkpoint signal.
"""

from __future__ import annotations

import logging
import random
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime

from src.configuration import GuardSettings, Paths
from src.tools import store

logger = logging.getLogger(__name__)

# Phrases/signals that mean "stop now" — account-safety responses from LinkedIn.
RATE_LIMIT_MARKERS = (
    "checkpoint/challenge",
    "rate limit",
    "too many requests",
    "you've reached",
    "unusual activity",
    "temporarily restricted",
    "account restricted",
)


class GuardHalt(RuntimeError):
    """Raised when the safety envelope says stop. Never swallowed silently."""


def detect_rate_limit_signal(text: str) -> str | None:
    """Return the matched marker if ``text`` looks like a rate-limit/checkpoint page.

    Pure so it is unit-testable without a browser (SPEC.md §6).
    """
    lowered = text.lower()
    for marker in RATE_LIMIT_MARKERS:
        if marker in lowered:
            return marker
    return None


class Guard:
    """The safety envelope. Every network/browser action passes through it.

    ``clock``, ``sleep`` and ``rng`` are injectable so tests are instant and
    deterministic (criterion: clock/sleep injectable).
    """

    def __init__(
        self,
        settings: GuardSettings,
        paths: Paths,
        conn: sqlite3.Connection,
        *,
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._settings = settings
        self._paths = paths
        self._conn = conn
        self._clock = clock
        self._sleep = sleep
        self._rng = rng or random.Random()

    # --- STOP sentinel ------------------------------------------------------

    def stop_requested(self) -> bool:
        """True if the human dropped the STOP sentinel file."""
        return self._paths.stop.exists()

    def check_stop(self) -> None:
        if self.stop_requested():
            raise GuardHalt(f"STOP sentinel present at {self._paths.stop}; halting run.")

    def trip_stop_sentinel(self) -> None:
        """Create the STOP sentinel so the halt survives this run."""
        self._paths.stop.parent.mkdir(parents=True, exist_ok=True)
        self._paths.stop.write_text("halted by guard\n", encoding="utf-8")

    # --- business hours -----------------------------------------------------

    def within_business_hours(self) -> bool:
        current = self._clock().time()
        return self._settings.hours_start <= current < self._settings.hours_end

    def assert_within_business_hours(self) -> None:
        if not self.within_business_hours():
            start = self._settings.hours_start.strftime("%H:%M")
            end = self._settings.hours_end.strftime("%H:%M")
            raise GuardHalt(
                f"Outside business hours ({start}-{end} local); refusing to start."
            )

    # --- daily cap ----------------------------------------------------------

    def applied_today(self) -> int:
        return store.count_applied_today(self._conn, today=self._clock().date())

    def remaining_today(self) -> int:
        return max(self._settings.daily_cap - self.applied_today(), 0)

    def assert_can_apply(self) -> None:
        used = self.applied_today()
        if used >= self._settings.daily_cap:
            raise GuardHalt(
                f"Daily cap reached ({used}/{self._settings.daily_cap}); "
                "no more applications today."
            )

    # --- pacing -------------------------------------------------------------

    def next_delay_seconds(self) -> float:
        return self._rng.uniform(
            self._settings.min_delay_seconds, self._settings.max_delay_seconds
        )

    def pause_between_actions(self) -> float:
        """Sleep a randomized 20-90s delay, checking STOP before and after."""
        self.check_stop()
        delay = self.next_delay_seconds()
        self._sleep(delay)
        self.check_stop()
        return delay

    # --- run start gate -----------------------------------------------------

    def assert_startable(self) -> None:
        """Refuse to start when stopped or outside business hours."""
        self.check_stop()
        self.assert_within_business_hours()

    # --- rate-limit / checkpoint signal ------------------------------------

    def check_page_text(self, text: str) -> None:
        """Halt and trip the sentinel if the page is a rate-limit/checkpoint page."""
        marker = detect_rate_limit_signal(text)
        if marker is not None:
            logger.warning("guard: rate-limit signal detected marker=%r", marker)
            self.trip_stop_sentinel()
            raise GuardHalt(
                f"LinkedIn rate-limit/checkpoint signal detected: {marker!r}; halting."
            )
