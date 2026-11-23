"""Opt-in headed browser verification of Task 30 metrics."""
import asyncio
import json
import os

import pytest

from src.configuration import SessionSettings, Settings
from src.tools.browser import _detach_session, build_browser
from src.tools.linkedin_status_overlay import StatusReporter

pytestmark = pytest.mark.skipif(not os.environ.get('AUTOJOB_TASK30_LIVE'),
                                reason='opt-in browser check')


async def test_metrics_preserve_activity_and_clicks(tmp_path, monkeypatch):
    browser = build_browser(Settings(data_dir=tmp_path, session=SessionSettings(headless=False)))
    await browser.start()
    reporter = None
    try:
        page = await browser.new_page()
        await page.goto('https://www.linkedin.com/login/')
        reporter = StatusReporter(page=page)
        reporter.step('Task 30 metrics verification')
        from src.tools.token_usage import TokenUsageTracker, runtime
        from src.tools.token_usage.applications import ApplicationCounts

        monkeypatch.setattr(runtime, 'applications', ApplicationCounts())
        monkeypatch.setattr(runtime, 'tracker', TokenUsageTracker({'test': (1, 2, None)}))
        monkeypatch.setattr(runtime, 'reporter', reporter)
        monkeypatch.setattr(runtime, 'submission', '')
        runtime.applications.scan('job:1')
        runtime.tracker.record('test', {'prompt_tokens': 100, 'completion_tokens': 20})
        runtime.freeze_submission()
        await reporter._pump_task
        runtime.applications.scan('job:2')
        runtime.tracker.record('test', {'prompt_tokens': 20, 'completion_tokens': 10})
        runtime.publish()
        await reporter._pump_task
        observed = json.loads(await page.evaluate('''() => JSON.stringify({
          activity: document.getElementById('autojob-status-current').textContent,
          live: document.getElementById('autojob-session-metrics').textContent,
          heading: document.getElementById('autojob-session-heading').textContent,
          frozen: !!document.getElementById('autojob-submission-metrics'),
          note: !!document.getElementById('autojob-usage-note'),
          pointer: getComputedStyle(document.getElementById('autojob-status')).pointerEvents,
          url: location.href
        })'''))
        assert observed['activity'] == 'Task 30 metrics verification'
        assert observed['heading'] == 'Current session info'
        assert observed['live'] == (
            'Total scanned: 2 | Submitted: 1 | Tokens used: 150 | Cost: $0.0002')
        assert not observed['frozen'] and not observed['note']
        assert observed['pointer'] == 'none'
        print(observed)
        await asyncio.sleep(1)
    finally:
        if reporter:
            await reporter.clear()
        await _detach_session(browser)
