"""Session token accounting; snapshots are independent immutable values."""

from dataclasses import dataclass
from decimal import Decimal
from threading import RLock


def _get(value, key, default=0):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


@dataclass(frozen=True)
class TokenUsage:
    input: int = 0
    output: int = 0
    cached: int = 0
    total: int = 0
    calls: int = 0
    unavailable: int = 0
    cost: float | None = 0.0


class TokenUsageTracker:
    def __init__(self, prices=None):
        self.prices = prices or {}
        self._models = {}
        self._lock = RLock()

    def record(self, model, usage):
        with self._lock:
            previous = self._models.get(model, TokenUsage())
            incoming = max(0, int(_get(usage, 'prompt_tokens') or 0))
            outgoing = max(0, int(_get(usage, 'completion_tokens') or 0))
            cached = min(incoming, max(0, int(_get(
                _get(usage, 'prompt_tokens_details', None), 'cached_tokens') or 0)))
            total = int(_get(usage, 'total_tokens', incoming + outgoing) or 0)
            prices = self.prices.get(model)
            cost = None
            if usage is not None and prices and prices[0] is not None and prices[1] is not None:
                rate_in, rate_out, rate_cached = map(
                    lambda v: Decimal(str(v)) if v is not None else None, prices)
                rate_cached = rate_in if rate_cached is None else rate_cached
                cost = float(((incoming - cached) * rate_in + cached * rate_cached
                              + outgoing * rate_out) / 1_000_000)
            self._models[model] = TokenUsage(
                previous.input + incoming, previous.output + outgoing,
                previous.cached + cached, previous.total + total, previous.calls + 1,
                previous.unavailable + (usage is None),
                None if previous.cost is None or cost is None else previous.cost + cost,
            )

    @property
    def per_model(self):
        with self._lock:
            return dict(self._models)

    def snapshot(self):
        values = list(self.per_model.values())
        counts = [sum(getattr(v, field) for v in values)
                  for field in ('input', 'output', 'cached', 'total', 'calls', 'unavailable')]
        cost = None if any(v.cost is None for v in values) else sum(v.cost for v in values)
        return TokenUsage(*counts, cost)

    @property
    def session_totals(self):
        return self.snapshot()


def format_metrics(usage, label='Session'):
    cost = 'unknown' if usage.cost is None else f'${usage.cost:.4f}'
    missing = ' · usage unavailable' if usage.unavailable else ''
    return (f'{label}: {usage.input:,} in / {usage.output:,} out '
            f'({usage.total:,} total) · Cost: {cost}{missing}')


def format_submission(usage):
    return format_metrics(usage, 'Up to submission')
