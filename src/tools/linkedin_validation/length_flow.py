"""Recheck a replacement control before entering a shortened answer."""

from src.state.text_shortening import TextShorteningAttempt
from src.tools.browser import _loads
from src.tools.linkedin_validation.conversion_flow import _LIVE_CONSTRAINTS
from src.tools.linkedin_validation.length_limit import shortening_value, units


def plan_shortening(field, source, outcome):
    candidate = shortening_value(field, source)
    audit = TextShorteningAttempt(
        question=field.get("question", ""),
        limit=int(field.get("maxlength") or 0),
        original_length=units(source),
        shortened_length=units(candidate) if candidate else 0,
    )
    outcome.validation.text_shortening_attempts.append(audit)
    return candidate, audit


async def recheck_shortening(element, field, source, candidate):
    live = _loads(await element.evaluate(_LIVE_CONSTRAINTS, candidate))
    if not live.get("fits"):
        return None
    fresh = {**field, **{key: value for key, value in live.items() if value is not None}}
    return candidate if shortening_value(fresh, source) == candidate else None
