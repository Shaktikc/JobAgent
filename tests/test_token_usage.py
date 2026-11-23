from concurrent.futures import ThreadPoolExecutor

from src.tools.token_usage import TokenUsageTracker, format_metrics


def test_accumulation_cached_cost_and_snapshot():
    tracker = TokenUsageTracker({'m': (2, 4, 1)})
    usage = dict(prompt_tokens=100, completion_tokens=20, total_tokens=120,
                 prompt_tokens_details={'cached_tokens': 40})
    tracker.record('m', usage)
    frozen = tracker.snapshot()
    with ThreadPoolExecutor() as pool:
        list(pool.map(lambda _: tracker.record('m', usage), range(10)))
    assert frozen.total == 120
    assert frozen.cost == 0.00024
    assert tracker.session_totals.total == 1320
    assert '120 total' in format_metrics(frozen)
    tracker.record('unknown', None)
    assert tracker.session_totals.cost is None
    assert tracker.session_totals.unavailable == 1
