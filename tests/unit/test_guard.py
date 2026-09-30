"""Unit tests for the safety envelope (Task 4).

Clock and sleep are injected, so every test is instant and deterministic. No
network, no browser: the daily cap reads an in-memory SQLite database.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from src.configuration import GuardSettings, Paths
from src.tools import store
from src.tools.guard import Guard, GuardHalt, detect_rate_limit_signal


def _paths(root: Path) -> Paths:
    data = root / "data"
    return Paths(
        root=root,
        config=root / "config",
        resumes=root / "resumes",
        data=data,
        db=data / "autojobapply.db",
        profile=data / "profile",
        artifacts=data / "artifacts",
        stop=data / "STOP",
    )


def _db() -> sqlite3.Connection:
    conn = store.connect(":memory:")
    store.init_db(conn)
    return conn


def _guard(
    paths: Paths,
    conn: sqlite3.Connection,
    *,
    now: datetime,
    sleep=None,
    seed: int = 7,
) -> Guard:
    return Guard(
        GuardSettings(),
        paths,
        conn,
        clock=lambda: now,
        sleep=sleep or (lambda _seconds: None),
        rng=random.Random(seed),
    )


def _record_applied(conn: sqlite3.Connection, day: datetime, count: int) -> None:
    for index in range(count):
        store.upsert_job(conn, store.Job(job_id=f"job-{index}"))
        store.set_job_status(conn, f"job-{index}", store.JobStatus.APPLIED)
    conn.execute(
        "UPDATE jobs SET applied_at = ?", (f"{day.date().isoformat()}T09:00:00+00:00",)
    )


# --- business hours ---------------------------------------------------------


def test_startable_inside_business_hours(tmp_path: Path) -> None:
    guard = _guard(_paths(tmp_path), _db(), now=datetime(2026, 9, 30, 10, 0))

    guard.assert_startable()  # must not raise


@pytest.mark.parametrize("hour", [0, 8, 18, 23])
def test_start_refused_outside_business_hours(tmp_path: Path, hour: int) -> None:
    guard = _guard(_paths(tmp_path), _db(), now=datetime(2026, 9, 30, hour, 0))

    with pytest.raises(GuardHalt, match="business hours"):
        guard.assert_startable()


# --- STOP sentinel ----------------------------------------------------------


def test_start_refused_when_stop_sentinel_exists(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.data.mkdir(parents=True)
    paths.stop.write_text("stop\n", encoding="utf-8")
    guard = _guard(paths, _db(), now=datetime(2026, 9, 30, 10, 0))

    with pytest.raises(GuardHalt, match="STOP"):
        guard.assert_startable()


def test_stop_sentinel_halts_the_next_action(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.data.mkdir(parents=True)
    paths.stop.write_text("stop\n", encoding="utf-8")
    guard = _guard(paths, _db(), now=datetime(2026, 9, 30, 10, 0))

    with pytest.raises(GuardHalt, match="STOP"):
        guard.pause_between_actions()


def test_stop_created_mid_pause_halts_after_sleep(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    def trip(_seconds: float) -> None:
        paths.data.mkdir(parents=True, exist_ok=True)
        paths.stop.write_text("stop\n", encoding="utf-8")

    guard = _guard(paths, _db(), now=datetime(2026, 9, 30, 10, 0), sleep=trip)

    with pytest.raises(GuardHalt, match="STOP"):
        guard.pause_between_actions()


# --- daily cap --------------------------------------------------------------


def test_thirtieth_application_allowed_but_thirty_first_refused(tmp_path: Path) -> None:
    conn = _db()
    now = datetime(2026, 9, 30, 10, 0)
    _record_applied(conn, now, 30)
    guard = _guard(_paths(tmp_path), conn, now=now)

    assert guard.applied_today() == 30
    assert guard.remaining_today() == 0
    with pytest.raises(GuardHalt, match="Daily cap reached"):
        guard.assert_can_apply()


def test_twenty_nine_applications_still_allowed(tmp_path: Path) -> None:
    conn = _db()
    now = datetime(2026, 9, 30, 10, 0)
    _record_applied(conn, now, 29)
    guard = _guard(_paths(tmp_path), conn, now=now)

    assert guard.remaining_today() == 1
    guard.assert_can_apply()  # must not raise


def test_previous_days_applications_do_not_count_toward_today(tmp_path: Path) -> None:
    conn = _db()
    _record_applied(conn, datetime(2026, 9, 29, 10, 0), 30)
    guard = _guard(_paths(tmp_path), conn, now=datetime(2026, 9, 30, 10, 0))

    assert guard.applied_today() == 0
    guard.assert_can_apply()  # must not raise


# --- pacing -----------------------------------------------------------------


def test_delay_is_within_the_configured_bounds(tmp_path: Path) -> None:
    guard = _guard(_paths(tmp_path), _db(), now=datetime(2026, 9, 30, 10, 0))

    for _ in range(50):
        assert 20 <= guard.next_delay_seconds() <= 90


def test_pause_between_actions_sleeps_the_computed_delay(tmp_path: Path) -> None:
    slept: list[float] = []
    guard = _guard(
        _paths(tmp_path),
        _db(),
        now=datetime(2026, 9, 30, 10, 0),
        sleep=slept.append,
    )

    delay = guard.pause_between_actions()

    assert slept == [delay]
    assert 20 <= delay <= 90


# --- rate-limit / checkpoint signal ----------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Please complete this security check. /checkpoint/challenge",
        "You've reached the weekly invitation limit",
        "Too many requests — try again later",
        "We noticed unusual activity on your account",
    ],
)
def test_detect_rate_limit_signal_finds_markers(text: str) -> None:
    assert detect_rate_limit_signal(text) is not None


def test_detect_rate_limit_signal_is_none_for_clean_text() -> None:
    assert detect_rate_limit_signal("Software Engineer at Acme Corp") is None


def test_rate_limit_signal_stops_the_run_and_trips_the_sentinel(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    guard = _guard(paths, _db(), now=datetime(2026, 9, 30, 10, 0))

    with pytest.raises(GuardHalt, match="rate-limit"):
        guard.check_page_text("LinkedIn: security checkpoint/challenge required")

    assert paths.stop.exists()
