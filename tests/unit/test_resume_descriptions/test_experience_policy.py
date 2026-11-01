"""Task 19: years-of-experience requirements never gate the resume match."""

from __future__ import annotations

import re

import pytest

from src.state import JobDescription
from src.tools.resume_descriptions import (
    ResumeDescription,
    build_match_messages,
    candidate_ids,
    neutralize_experience_requirements,
    profile_for_match,
)


@pytest.mark.parametrize(
    "text",
    [
        "Minimum 10 years of experience required. Python AWS",
        "5-8 years of experience with Python and AWS",
        "5\u20138 years of experience",
        "at least 8 years of experience",
        "minimum of 5 years",
        "10 yrs experience",
        "experience required: 10 years",
        "10 years of relevant professional industry experience",
        "ten years of experience",
        "10+ years of experience with Python and AWS",
        "10+ years building distributed systems",
        "we have served clients for 10 years",
        "3 years of experience with Python",
    ],
)
def test_numeric_years_are_removed_from_the_match_view(text: str) -> None:
    cleaned = neutralize_experience_requirements(text)

    assert re.search(
        r"(?i)\b(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
        r"nineteen|twenty)\s*(?:\+)?\s*(?:years?|yrs?\.?)",
        cleaned,
    ) is None


def test_non_experience_requirement_words_are_preserved() -> None:
    cleaned = neutralize_experience_requirements(
        "Minimum 10 years of experience with Python and AWS in fintech"
    )

    assert "Python" in cleaned
    assert "AWS" in cleaned
    assert "fintech" in cleaned
    assert "10" not in cleaned


def test_text_without_a_years_requirement_is_unchanged() -> None:
    text = "Python, AWS, and fintech experience preferred."
    assert neutralize_experience_requirements(text) == text


def test_match_input_omits_years_and_neutralises_the_job_body() -> None:
    candidates = [
        ("a.pdf", ResumeDescription(summary="Backend", years_experience=7)),
    ]

    messages = build_match_messages(
        JobDescription(
            title="Backend Engineer",
            body="Minimum 10 years of experience with Python and AWS.",
        ),
        candidates,
        candidate_ids(candidates),
    )
    user = messages[1]["content"]

    assert "10 years" not in user
    assert "years_experience" not in user
    assert "Python" in user and "AWS" in user
    assert "Backend" in user


def test_profile_for_match_omits_years_but_keeps_other_fields() -> None:
    description = ResumeDescription(
        summary="Backend",
        skills=["Python"],
        titles=["Engineer"],
        seniority="senior",
        years_experience=7,
        domain="fintech",
        highlights=["Led a platform team"],
        ai_coding_tools=["Cursor"],
    )

    profile = profile_for_match(description)

    assert "years_experience" not in profile
    assert profile["summary"] == "Backend"
    assert profile["skills"] == ["Python"]
    assert profile["highlights"] == ["Led a platform team"]
    assert profile["ai_coding_tools"] == ["Cursor"]


def test_match_prompt_declares_years_non_blocking() -> None:
    candidates = [("a.pdf", ResumeDescription(summary="Backend"))]
    messages = build_match_messages(
        JobDescription(title="X"), candidates, candidate_ids(candidates)
    )
    prompt = messages[0]["content"].lower()

    assert "years-of-experience requirements are non-blocking" in prompt
    assert "never compare" in prompt
