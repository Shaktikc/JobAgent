from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.tools.token_usage import TokenUsageTracker, runtime
from src.tools.token_usage.pricing import load_prices


@pytest.mark.asyncio
async def test_calls_failures_freeze_and_continuing_totals(monkeypatch):
    tracker = TokenUsageTracker({'m': (1, 2, None)})
    monkeypatch.setattr(runtime, 'tracker', tracker)
    monkeypatch.setattr(runtime, 'reporter', None)
    monkeypatch.setattr(runtime, 'submission', '')
    response = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10,
                                                     total_tokens=110))
    create = AsyncMock(side_effect=[response, response, RuntimeError('offline')])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    await runtime.tracked_completion(client, model='m')
    runtime.freeze_submission()
    frozen = runtime.submission
    await runtime.tracked_completion(client, model='m')
    assert runtime.submission == frozen
    assert tracker.snapshot().total == 220
    with pytest.raises(RuntimeError):
        await runtime.tracked_completion(client, model='m')
    assert tracker.snapshot().calls == 3
    assert tracker.snapshot().unavailable == 1


def test_pricing_api_cache_and_fallback(monkeypatch):
    import io

    from src.tools.token_usage import pricing

    calls = []

    def fetch(*args, **kwargs):
        calls.append(args)
        return io.StringIO('{"data":[{"id":"m","pricing":{"prompt":"0.000002",'
                           '"completion":"0.000004"}}]}')

    load_prices.cache_clear()
    monkeypatch.setattr(pricing, 'urlopen', fetch)
    try:
        assert load_prices()['m'] == (2, 4, None)
        assert load_prices()['m'] == (2, 4, None)
        assert len(calls) == 1
        assert load_prices()['xiaomi/mimo-v2.6-pro'] == (None, None, None)
    finally:
        load_prices.cache_clear()


async def test_reporter_without_page_and_repair_usage(monkeypatch):
    from src.tools.linkedin_status_overlay import StatusReporter
    from src.tools.token_usage.repair_usage import record_repair_usage

    status = StatusReporter()
    status.step('Filling the form')
    status.metrics('Session: 10 tokens')
    assert status._latest == ('agent', 'Filling the form')

    tracker = TokenUsageTracker({'m': (1, 2, None)})
    monkeypatch.setattr(runtime, 'tracker', tracker)
    monkeypatch.setattr(runtime, 'reporter', status)
    count = record_repair_usage(
        'ordinary log\n{"usage":{"prompt_tokens":100,"completion_tokens":20}}', 'm')
    assert count == 1
    assert tracker.snapshot().total == 120
    assert status._latest == ('agent', 'Filling the form')


async def test_resume_retry_and_answer_calls_are_accounted(monkeypatch):
    from src.configuration import LLMSettings
    from src.tools.llm_answers import LLMAnswerChooser
    from src.tools.resume_descriptions.client import _ask_json
    from src.tools.resume_descriptions.models import ResumeDescriptionError

    tracker = TokenUsageTracker({'m': (1, 2, None)})
    monkeypatch.setattr(runtime, 'tracker', tracker)
    monkeypatch.setattr(runtime, 'reporter', None)
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        choices=[SimpleNamespace(message=SimpleNamespace(content='{}'))])
    create = AsyncMock(return_value=response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    attempts = []

    def parse(text):
        attempts.append(text)
        if len(attempts) == 1:
            raise ResumeDescriptionError('retry JSON')
        return text

    settings = LLMSettings(model='m', api_key='fake')
    await _ask_json(client, settings, [], parse)
    chooser = LLMAnswerChooser(settings, {'Name': 'Test'})
    chooser._client = client
    await chooser('Name?', 'text', [])
    assert tracker.snapshot().calls == 3
    assert tracker.snapshot().total == 45
