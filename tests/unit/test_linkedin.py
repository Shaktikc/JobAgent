"""Unit tests for pure LinkedIn URL/text helpers."""

from __future__ import annotations

from src.tools.linkedin import (
    build_jobs_search_url,
    is_linkedin_url,
    is_logged_in_path,
    is_login_path,
    looks_like_easy_apply,
    looks_like_jobs_search_input,
    pick_easy_apply_index,
)


def test_is_linkedin_url() -> None:
    assert is_linkedin_url("https://www.linkedin.com/login/")
    assert is_linkedin_url("https://au.linkedin.com/jobs/search/?keywords=x")
    assert not is_linkedin_url("https://example.com/login")
    assert not is_linkedin_url("not a url")
    assert not is_linkedin_url("")


def test_build_jobs_search_url_encodes_the_query() -> None:
    url = build_jobs_search_url("software engineer")
    assert url == "https://www.linkedin.com/jobs/search/?keywords=software+engineer"
    assert build_jobs_search_url("  data scientist  ").endswith("keywords=data+scientist")


def test_is_login_path() -> None:
    assert is_login_path("/login")
    assert is_login_path("/uas/login")
    assert is_login_path("/checkpoint/challenge")
    assert is_login_path("/authwall")
    assert not is_login_path("/feed/")


def test_is_logged_in_path() -> None:
    assert is_logged_in_path("/feed/")
    assert is_logged_in_path("/jobs/search/")
    assert is_logged_in_path("/in/somebody")
    assert not is_logged_in_path("/login")
    assert not is_logged_in_path("/")
    assert not is_logged_in_path("")


def test_looks_like_easy_apply_requires_easy_apply() -> None:
    assert looks_like_easy_apply("Easy Apply")
    assert looks_like_easy_apply("  Easy   Apply filter. ")
    assert not looks_like_easy_apply("Apply on company website")
    assert not looks_like_easy_apply("Save")


def test_pick_easy_apply_index() -> None:
    assert pick_easy_apply_index(["Apply", "Save", "Easy Apply"]) == 2
    assert pick_easy_apply_index(["Apply", "Save"]) is None
    assert pick_easy_apply_index([]) is None


def test_looks_like_jobs_search_input() -> None:
    assert looks_like_jobs_search_input("Search by title, skill, or company")
    assert looks_like_jobs_search_input("search jobs")
    assert not looks_like_jobs_search_input("City, state, or zip code")
    assert not looks_like_jobs_search_input("")
