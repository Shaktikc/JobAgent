"""The match prompt and parsing the LLM's single-choice + per-candidate reply."""

from __future__ import annotations

import pytest

from src.state import JobDescription
from src.tools.resume_descriptions import (
    ResumeDescription,
    ResumeDescriptionError,
    build_match_messages,
    candidate_ids,
    parse_match,
)


def test_candidate_ids_are_stable_and_ordered() -> None:
    ids = candidate_ids([("a.pdf", ResumeDescription()), ("b.pdf", ResumeDescription())])
    assert ids == {"c1": "a.pdf", "c2": "b.pdf"}


def test_build_match_messages_list_the_job_and_candidates() -> None:
    candidates = [
        ("a.pdf", ResumeDescription(summary="Cloud", skills=["AWS"])),
        ("b.pdf", ResumeDescription(summary="Frontend", skills=["React"])),
    ]
    ids = candidate_ids(candidates)

    messages = build_match_messages(
        JobDescription(title="Cloud Engineer", company="Acme", body="AWS and Docker"),
        candidates,
        ids,
    )

    assert messages[0]["role"] == "system"
    user = messages[1]["content"]
    assert "Cloud Engineer" in user
    assert "Acme" in user
    assert "AWS and Docker" in user
    assert "c1" in user and "c2" in user


def test_parse_match_chooses_a_candidate() -> None:
    ids = {"c1": "a.pdf", "c2": "b.pdf"}
    match = parse_match(
        '{"choice": "c2", "fit": "strong", "rationale": "best fit"}', ids
    )

    assert match.selected_path == "b.pdf"
    assert match.fit == "strong"
    assert match.is_strong is True
    assert match.rationale == "best fit"
    assert match.candidate_ids == ids


def test_parse_match_normalises_the_fit_rating() -> None:
    ids = {"c1": "a.pdf"}
    assert parse_match('{"choice": "c1", "fit": "PARTIAL"}', ids).fit == "partial"
    assert parse_match('{"choice": "c1", "fit": " Strong "}', ids).fit == "strong"
    # An unknown/missing rating fails closed (it is not a strong match).
    assert parse_match('{"choice": "c1", "fit": "excellent"}', ids).fit == ""
    assert parse_match('{"choice": "c1"}', ids).is_strong is False


def test_parse_match_none_or_unknown_id_is_a_no_match() -> None:
    ids = {"c1": "a.pdf"}
    assert parse_match('{"choice": "none"}', ids).selected_path is None
    assert parse_match('{"choice": "c9"}', ids).selected_path is None
    assert parse_match('{"choice": ""}', ids).selected_path is None
    assert parse_match('{"choice": "none"}', ids).fit == "none"


def test_parse_match_uses_a_strong_rating_when_the_single_choice_is_partial() -> None:
    # The model names the thematically closer AI resume as its choice (partial),
    # but its own per-candidate ratings say the full-stack resume is strong.
    ids = {"c1": "ai.pdf", "c4": "fullstack.pdf"}
    match = parse_match(
        '{"ratings": {"c1": "partial", "c4": "strong"}, "choice": "c1", '
        '"fit": "partial", "rationale": "AI title looks closest"}',
        ids,
    )

    assert match.selected_path == "fullstack.pdf"
    assert match.fit == "strong"
    assert match.is_strong is True
    assert "c4" in match.rationale and "partial" in match.rationale


def test_parse_match_accepts_a_list_of_ratings() -> None:
    ids = {"c1": "ai.pdf", "c4": "fullstack.pdf"}
    match = parse_match(
        '{"ratings": [{"id": "c1", "fit": "partial"}, '
        '{"id": "c4", "fit": "strong fit"}], "choice": "c1", "fit": "partial"}',
        ids,
    )

    assert match.selected_path == "fullstack.pdf"
    assert match.fit == "strong"
    assert match.ratings == {"c1": "partial", "c4": "strong"}


def test_parse_match_keeps_a_partial_choice_when_nothing_is_strong() -> None:
    ids = {"c1": "ai.pdf", "c4": "fullstack.pdf"}
    match = parse_match(
        '{"ratings": {"c1": "partial", "c4": "partial"}, "choice": "c1", '
        '"fit": "partial", "rationale": "neither covers the stack"}',
        ids,
    )

    assert match.selected_path == "ai.pdf"
    assert match.fit == "partial"
    assert match.is_strong is False


def test_parse_match_ignores_unknown_rating_ids() -> None:
    ids = {"c1": "a.pdf"}
    match = parse_match(
        '{"ratings": {"c9": "strong"}, "choice": "c1", "fit": "partial"}',
        ids,
    )

    assert match.selected_path == "a.pdf"
    assert match.fit == "partial"
    assert match.ratings == {}


def test_build_match_messages_ask_for_a_fit_rating() -> None:
    candidates = [("a.pdf", ResumeDescription(summary="Cloud", skills=["AWS"]))]
    messages = build_match_messages(JobDescription(title="X"), candidates, {"c1": "a.pdf"})
    assert '"fit"' in messages[0]["content"]
    assert "strong" in messages[0]["content"]
    assert '"ratings"' in messages[0]["content"]
    assert "rate every candidate" in messages[0]["content"].lower()


def test_build_match_messages_include_the_richer_profile_fields() -> None:
    candidates = [
        (
            "a.pdf",
            ResumeDescription(
                summary="Senior engineer",
                highlights=["Led a platform team"],
                ai_coding_tools=["Cursor"],
            ),
        )
    ]
    messages = build_match_messages(JobDescription(title="X"), candidates, {"c1": "a.pdf"})
    user = messages[1]["content"]

    assert "Led a platform team" in user
    assert "Cursor" in user
    assert "highlights" in user and "ai_coding_tools" in user


def test_parse_match_rejects_an_unusable_reply() -> None:
    with pytest.raises(ResumeDescriptionError):
        parse_match("not json at all", {"c1": "a.pdf"})


def test_parse_match_finds_the_answer_after_an_example_object() -> None:
    # The old greedy ``{.*}`` regex swallowed both objects and failed to parse.
    ids = {"c1": "a.pdf"}
    text = 'Example {"choice": "c9"}.\nFinal: {"choice": "c1", "rationale": "fits {stack}"}.'
    match = parse_match(text, ids)

    assert match.selected_path == "a.pdf"
    assert match.rationale == "fits {stack}"
