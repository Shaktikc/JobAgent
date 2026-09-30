"""`answering` — map resume text and facts onto Easy Apply form questions.

Implemented in two parts:
- Task 6: deterministic facts rule engine and the ``Answer`` type carrying
  provenance and confidence (no LLM).
- Task 10: LLM integration behind the rules, with a confidence threshold that
  turns low-confidence answers into ``NEEDS_REVIEW`` rather than guesses.

Rules always take precedence over the LLM. Every field yields exactly one answer
with a ``Provenance`` value; nothing is ever left silently empty (SPEC.md §5, §7).

This module is pure: it receives a validated :class:`~src.configuration.FactsConfig`
and never reads files or the environment itself.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from src.configuration import FactsConfig, FactsRule
from src.tools.store import Answer, Provenance

# Confidence by provenance. Rules and resume facts are deterministic; a guess
# carries whatever the LLM reported (or a conservative default); an unanswered
# field is pinned to zero and must surface at review.
FACTS_RULE_CONFIDENCE = 1.0
RESUME_CONFIDENCE = 1.0
NEEDS_REVIEW_CONFIDENCE = 0.0
DEFAULT_GUESS_CONFIDENCE = 0.5


def _stringify(value: Any) -> str | None:
    """Render a fact for a form field: booleans as Yes/No, everything else as str."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def resolve_fact_path(facts: Mapping[str, Any], path: str) -> Any:
    """Resolve a dotted fact path such as ``facts.desired_salary``.

    The leading ``facts`` segment from the SPEC's ``answer_from`` syntax is
    optional; returns ``None`` when any segment is missing.
    """
    segments = path.split(".")
    if segments and segments[0] == "facts":
        segments = segments[1:]
    current: Any = facts
    for segment in segments:
        if not isinstance(current, Mapping) or segment not in current:
            return None
        current = current[segment]
    return current


def match_rule(field: str, rules: Sequence[FactsRule]) -> FactsRule | None:
    """Return the first hard rule whose regex matches ``field`` (case-insensitive)."""
    for rule in rules:
        try:
            if re.search(rule.match, field, re.IGNORECASE):
                return rule
        except re.error as exc:  # a malformed rule is a config error, not a crash
            raise ValueError(f"invalid facts rule regex: {rule.match!r}") from exc
    return None


def rule_value(rule: FactsRule, facts: Mapping[str, Any]) -> str | None:
    """The answer a matched rule supplies: a literal, or a resolved fact."""
    if rule.answer is not None:
        return rule.answer
    if rule.answer_from is not None:
        return _stringify(resolve_fact_path(facts, rule.answer_from))
    return None


def _validate_confidence(value: float) -> float:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"confidence must be within [0.0, 1.0], got {value!r}")
    return value


def answer_field(
    field: str,
    config: FactsConfig,
    *,
    resume_value: str | None = None,
    guess_value: str | None = None,
    guess_confidence: float = DEFAULT_GUESS_CONFIDENCE,
) -> Answer:
    """Produce exactly one :class:`Answer` for a form field.

    Precedence (SPEC.md §7): a matched hard rule, then a resume-derived fact, then
    an LLM guess. A field none of these covers is returned as ``NEEDS_REVIEW`` with
    an empty value — never left silently empty. A rule that matches always claims
    the field, even if the LLM also supplied a value.
    """
    rule = match_rule(field, config.rules)
    if rule is not None:
        value = rule_value(rule, config.facts)
        if value is not None:
            return Answer(field, value, Provenance.FACTS_RULE, FACTS_RULE_CONFIDENCE)
        # The rule owns this field but has no usable value: surface it, do not guess.
        return Answer(field, "", Provenance.NEEDS_REVIEW, NEEDS_REVIEW_CONFIDENCE)

    if resume_value:
        return Answer(field, resume_value, Provenance.RESUME, RESUME_CONFIDENCE)

    if guess_value:
        return Answer(
            field,
            guess_value,
            Provenance.LLM_GUESS,
            _validate_confidence(guess_confidence),
        )

    return Answer(field, "", Provenance.NEEDS_REVIEW, NEEDS_REVIEW_CONFIDENCE)


def answer_fields(
    fields: Sequence[str],
    config: FactsConfig,
    *,
    resume_values: Mapping[str, str] | None = None,
    guess_values: Mapping[str, str] | None = None,
) -> list[Answer]:
    """Answer every field in order, returning exactly one :class:`Answer` per field."""
    resume_values = resume_values or {}
    guess_values = guess_values or {}
    return [
        answer_field(
            field,
            config,
            resume_value=resume_values.get(field),
            guess_value=guess_values.get(field),
        )
        for field in fields
    ]
