"""Public OpenRouter prices, fetched once with an offline fallback."""
import json
from functools import lru_cache
from urllib.request import urlopen

from src.configuration import PROJECT_ROOT


@lru_cache(maxsize=1)
def load_prices():
    prices = {}
    try:
        data = json.loads((PROJECT_ROOT / 'data/model_pricing.json').read_text())
        prices = {model: tuple(row.get(key) for key in (
            'input_per_million', 'output_per_million', 'cached_input_per_million'))
            for model, row in data.items()}
    except (OSError, ValueError, AttributeError):
        pass
    try:
        with urlopen('https://openrouter.ai/api/v1/models', timeout=5) as response:
            data = json.load(response)
        for row in data['data']:
            price = row.get('pricing', {})
            rates = tuple(float(price[key]) * 1_000_000 if price.get(key) is not None
                          else None for key in ('prompt', 'completion', 'input_cache_read'))
            if rates[0] is not None and rates[1] is not None:
                prices[row['id']] = rates
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return prices
