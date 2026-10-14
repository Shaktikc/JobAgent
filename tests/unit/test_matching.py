"""Unit tests for the keyword helpers used by Task 3.1's job profiles."""

from __future__ import annotations

from src.tools.matching import find_seniority, skills_in_text, title_tokens


def test_skills_in_text_finds_whole_tokens_only() -> None:
    assert skills_in_text("Python, AWS and Docker") == ["aws", "docker", "python"]
    # "go" must not match inside "google".
    assert "go" not in skills_in_text("I love google search")


def test_find_seniority_picks_the_highest_level() -> None:
    assert find_seniority("Senior Software Engineer") == "senior"
    assert find_seniority("Principal Staff Engineer") == "principal"
    assert find_seniority("Web developer") == ""


def test_title_tokens_drop_stopwords_and_short_words() -> None:
    assert title_tokens("Senior Python Engineer") == ["senior", "python", "engineer"]
    assert title_tokens("Head of Engineering") == ["head", "engineering"]
    assert title_tokens("") == []
