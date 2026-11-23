"""Accounting for the application's single active browser session."""
import asyncio

from . import TokenUsageTracker, format_submission
from .applications import ApplicationCounts
from .display import format_session_info
from .pricing import load_prices

tracker = TokenUsageTracker()
reporter = None
submission = ''
applications = ApplicationCounts()


def reset_session(prices=None):
    """Reset accounting explicitly for a new run or isolated test."""
    global tracker, reporter, submission, applications
    tracker = TokenUsageTracker(prices)
    reporter = None
    submission = ''
    applications = ApplicationCounts()
    return tracker


async def start_session(status):
    global reporter
    reset_session(await asyncio.to_thread(load_prices))
    reporter = status
    publish()


def publish():
    method = getattr(reporter, 'metrics', None)
    if callable(method):
        try:
            method(format_session_info(tracker.snapshot(), applications))
        except Exception:  # best-effort browser feedback
            pass


def freeze_submission():
    global submission
    applications.confirm()
    submission = f'{format_submission(tracker.snapshot())} | {applications.format()}'
    publish()


async def tracked_completion(client, **kwargs):
    try:
        response = await client.chat.completions.create(**kwargs)
    except Exception:
        tracker.record(kwargs['model'], None)
        publish()
        raise
    tracker.record(kwargs['model'], getattr(response, 'usage', None))
    publish()
    return response
