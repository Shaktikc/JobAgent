"""Unit tests for the pure resume-to-job matching engine."""

from __future__ import annotations

from src.tools.matching import (
    MatchResult,
    find_seniority,
    score_resume,
    skills_in_text,
)


def test_skills_in_text_finds_whole_tokens_only() -> None:
    assert skills_in_text("Python, AWS and Docker") == ["aws", "docker", "python"]
    # "go" must not match inside "google".
    assert "go" not in skills_in_text("I love google search")


def test_score_resume_rewards_shared_skills() -> None:
    job = "We build services with Python, AWS and Docker."
    strong = score_resume("Backend Engineer", job, "Python AWS Docker engineer")
    weak = score_resume("Backend Engineer", job, "Sales and marketing manager")

    assert isinstance(strong, MatchResult)
    assert strong.score > weak.score
    assert set(strong.matched_skills) >= {"python", "aws", "docker"}
    assert weak.score == 0.0


def test_score_resume_rewards_title_overlap() -> None:
    job = "Python developer role"
    with_title = score_resume("Senior Software Engineer", job, "senior software engineer")
    without_title = score_resume("Senior Software Engineer", job, "chef and baker")

    assert with_title.score > without_title.score
    assert "software" in with_title.title_hits
    assert "engineer" in with_title.title_hits


def test_score_resume_rewards_seniority_match() -> None:
    job = "Build things with Python"
    matched = score_resume("Senior Python Engineer", job, "Senior engineer, Python")
    unmatched = score_resume("Senior Python Engineer", job, "Junior engineer, Python")

    assert matched.seniority == "senior"
    assert matched.seniority_matched is True
    assert matched.score > unmatched.score


def test_score_resume_rewards_experience_fit() -> None:
    job = "Requires Python and 5+ years of experience."
    enough = score_resume("Engineer", job, "Python developer with 8 years")
    too_little = score_resume("Engineer", job, "Python developer with 1 year")

    assert enough.required_years == 5
    assert enough.resume_years == 8
    assert enough.components["experience"] > too_little.components["experience"]


def test_find_seniority_picks_the_highest_level() -> None:
    assert find_seniority("Senior Software Engineer") == "senior"
    assert find_seniority("Principal Staff Engineer") == "principal"
    assert find_seniority("Web developer") == ""


def test_rationale_is_explainable() -> None:
    job = "Senior Python engineer with AWS and 5+ years."
    result = score_resume("Senior Python Engineer", job, "Senior Python AWS developer, 7 years")

    assert result.rationale
    assert "shared skills" in result.rationale
    assert "seniority" in result.rationale


def test_scoring_is_deterministic() -> None:
    job = "Python, AWS, Docker, Kubernetes"
    resume = "Python AWS Docker"
    first = score_resume("Platform Engineer", job, resume)
    second = score_resume("Platform Engineer", job, resume)

    assert first == second
