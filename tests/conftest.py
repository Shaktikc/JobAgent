"""Shared test isolation.

Task 33: tests must never write into the real ``data/crash_logs`` or
``data/logs``. Crash logging is disabled by default here; the Task 33 tests turn it
on explicitly against ``tmp_path``. The process-wide crash context and hooks are
reset after every test.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_crash_logs(monkeypatch):
    monkeypatch.setenv("AUTOJOB_CRASH_LOG_ENABLED", "false")
    from src.tools.crash_logs import uninstall_crash_logging

    uninstall_crash_logging()
    yield
    uninstall_crash_logging()
