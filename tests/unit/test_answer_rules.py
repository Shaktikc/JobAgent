"""Unit tests for the deterministic `answering` rule engine (Task 6).

No network, no browser, no LLM: a `FactsConfig` is built in-memory (or loaded from
the real `config/facts.yaml`) and every field must yield exactly one `Answer`
carrying a `Provenance` and a confidence (SPEC.md §5, §7).
"""

from __future__ import annotations

import pytest

from src.configuration import REPO_ROOT, FactsConfig, FactsRule
from src.nodes.answer import (
    FACTS_RULE_CONFIDENCE,
    NEEDS_REVIEW_CONFIDENCE,
    RESUME_CONFIDENCE,
    answer_field,
    answer_fields,
    match_rule,
    rule_value,
)
from src.tools.store import Answer, Provenance

FACTS_PATH = REPO_ROOT / "config" / "facts.yaml"

PROVENANCES = {p.value for p in Provenance}


def _config() -> FactsConfig:
    return FactsConfig(
        facts={
            "work_authorization": "US citizen",
            "requires_sponsorship": False,
            "notice_period": "2 weeks",
            "desired_salary": "110000",
            "years_experience": 4,
        },
        rules=[
            FactsRule(match="sponsor", answer="No"),
            FactsRule(match="salary|compensation|expected pay", answer_from="facts.desired_salary"),
            FactsRule(match="notice period|when can you start", answer_from="facts.notice_period"),
        ],
    )


# --- config loading ---------------------------------------------------------


def test_real_facts_yaml_loads_and_validates() -> None:
    config = FactsConfig.from_yaml(FACTS_PATH)

    assert config.facts["work_authorization"]
    assert config.rules, "facts.yaml must define at least one hard rule"
    assert all(rule.match for rule in config.rules)


# --- regex matching ---------------------------------------------------------


def test_match_rule_is_case_insensitive_and_searches() -> None:
    config = _config()

    matched = match_rule("Do you require sponsorship now or in the future?", config.rules)

    assert matched is not None
    assert matched.answer == "No"


def test_match_rule_returns_none_when_nothing_matches() -> None:
    assert match_rule("What is your favorite color?", _config().rules) is None


# --- rule values ------------------------------------------------------------


def test_rule_value_prefers_literal_answer() -> None:
    rule = FactsRule(match="sponsor", answer="No")

    assert rule_value(rule, _config().facts) == "No"


def test_rule_value_resolves_answer_from_facts() -> None:
    rule = FactsRule(match="salary", answer_from="facts.desired_salary")

    assert rule_value(rule, _config().facts) == "110000"


def test_rule_value_renders_booleans_as_yes_no() -> None:
    rule = FactsRule(match="sponsor", answer_from="facts.requires_sponsorship")

    assert rule_value(rule, _config().facts) == "No"


def test_rule_value_renders_int_as_string() -> None:
    rule = FactsRule(match="experience", answer_from="facts.years_experience")

    assert rule_value(rule, _config().facts) == "4"


def test_rule_value_returns_none_for_unknown_fact() -> None:
    rule = FactsRule(match="x", answer_from="facts.does_not_exist")

    assert rule_value(rule, _config().facts) is None


# --- one answer per field, with provenance ----------------------------------


def test_rule_matched_field_is_facts_rule_with_full_confidence() -> None:
    answer = answer_field("Do you require sponsorship?", _config())

    assert answer == Answer(
        field="Do you require sponsorship?",
        value="No",
        provenance=Provenance.FACTS_RULE,
        confidence=FACTS_RULE_CONFIDENCE,
    )


def test_answer_from_rule_yields_the_fact_value() -> None:
    answer = answer_field("Expected salary / compensation", _config())

    assert answer.provenance is Provenance.FACTS_RULE
    assert answer.value == "110000"


def test_unmatched_field_is_needs_review_and_never_silently_empty() -> None:
    answer = answer_field("What is your favorite color?", _config())

    assert answer.provenance is Provenance.NEEDS_REVIEW
    assert answer.value == ""
    assert answer.confidence == NEEDS_REVIEW_CONFIDENCE


def test_resume_value_used_when_no_rule_matches() -> None:
    answer = answer_field("City", _config(), resume_value="Boston")

    assert answer.provenance is Provenance.RESUME
    assert answer.value == "Boston"
    assert answer.confidence == RESUME_CONFIDENCE


def test_llm_guess_used_only_when_no_rule_or_resume() -> None:
    answer = answer_field("Favorite editor", _config(), guess_value="vim", guess_confidence=0.4)

    assert answer.provenance is Provenance.LLM_GUESS
    assert answer.value == "vim"
    assert answer.confidence == 0.4


def test_rules_take_precedence_over_llm_output() -> None:
    """Criterion 5: a matched rule wins even when an LLM guess is supplied."""
    answer = answer_field(
        "Do you need sponsorship?",
        _config(),
        resume_value="Maybe",
        guess_value="Yes",
    )

    assert answer.provenance is Provenance.FACTS_RULE
    assert answer.value == "No"


def test_empty_resume_value_is_not_an_answer() -> None:
    answer = answer_field("City", _config(), resume_value="")

    assert answer.provenance is Provenance.NEEDS_REVIEW


def test_matched_rule_with_missing_fact_does_not_fall_through_to_guess() -> None:
    config = FactsConfig(facts={}, rules=[FactsRule(match="salary", answer_from="facts.salary")])

    answer = answer_field("Expected salary", config, guess_value="100000")

    assert answer.provenance is Provenance.NEEDS_REVIEW
    assert answer.value == ""


# --- batch: exactly one answer per field ------------------------------------


def test_answer_fields_returns_one_answer_per_field_in_order() -> None:
    fields = ["Expected salary", "Sponsorship?", "Favorite color"]

    answers = answer_fields(fields, _config())

    assert [a.field for a in answers] == fields
    assert len(answers) == len(fields)


def test_answer_fields_provenance_is_always_one_of_the_four() -> None:
    answers = answer_fields(["Sponsorship?", "Favorite color"], _config())

    assert all(answer.provenance.value in PROVENANCES for answer in answers)


def test_answer_fields_uses_per_field_resume_and_guess_maps() -> None:
    answers = answer_fields(
        ["City", "Favorite editor"],
        _config(),
        resume_values={"City": "Boston"},
        guess_values={"Favorite editor": "vim"},
    )

    by_field = {a.field: a for a in answers}
    assert by_field["City"].provenance is Provenance.RESUME
    assert by_field["Favorite editor"].provenance is Provenance.LLM_GUESS


def test_confidence_is_always_within_zero_and_one() -> None:
    answers = answer_fields(
        ["Sponsorship?", "City", "Favorite editor", "Unknown"],
        _config(),
        resume_values={"City": "Boston"},
        guess_values={"Favorite editor": "vim"},
    )

    assert all(0.0 <= a.confidence <= 1.0 for a in answers)


def test_answer_type_is_the_shared_store_answer() -> None:
    # The engine must emit the frozen contract, not a look-alike.
    assert isinstance(answer_field("Sponsorship?", _config()), Answer)


@pytest.mark.parametrize("bad_confidence", [-0.1, 1.1])
def test_guess_confidence_outside_range_is_rejected(bad_confidence: float) -> None:
    with pytest.raises(ValueError):
        answer_field(
            "Favorite editor",
            _config(),
            guess_value="vim",
            guess_confidence=bad_confidence,
        )
