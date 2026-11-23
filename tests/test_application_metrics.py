from src.tools.token_usage import runtime
from src.tools.token_usage.applications import ApplicationCounts


def test_unique_scans_confirmations_and_frozen_counts(monkeypatch):
    counts = ApplicationCounts()
    monkeypatch.setattr(runtime, 'applications', counts)
    monkeypatch.setattr(runtime, 'reporter', None)
    monkeypatch.setattr(runtime, 'submission', '')
    counts.scan('job:1')
    counts.scan('job:1')
    assert counts.scanned == 1
    runtime.freeze_submission()
    frozen = runtime.submission
    assert 'Scanned: 1' in frozen and 'Submitted: 1' in frozen
    runtime.freeze_submission()
    assert counts.submitted == 1
    counts.scan('job:2')
    assert counts.scanned == 2 and counts.submitted == 1
    assert runtime.submission == frozen
    runtime.freeze_submission()
    assert counts.submitted == 2


def test_reset_clears_application_counts():
    runtime.applications.scan('job:reset')
    runtime.reset_session()
    assert runtime.applications.scanned == runtime.applications.submitted == 0


async def test_card_identity_survives_repeated_results_scans(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.tools.token_usage.applications import record_scan

    counts = ApplicationCounts()
    monkeypatch.setattr(runtime, 'applications', counts)
    monkeypatch.setattr(runtime, 'reporter', None)
    card = SimpleNamespace(evaluate=AsyncMock(return_value='12345'))
    page = SimpleNamespace(get_url=AsyncMock(return_value='https://www.linkedin.com/jobs/'))
    await record_scan(page, card, 'first-index')
    await record_scan(page, card, 'different-index')
    assert counts.scanned == 1
    assert counts.current == 'job:12345'
