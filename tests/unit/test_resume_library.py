"""Unit tests for the human-provided resume library (Task 3.1, no browser)."""

from __future__ import annotations

import pytest

from src.state import JobDescription
from src.tools.resume_library import (
    find_reusable_resume,
    job_profile,
    load_library,
    profile_similarity,
    remember_resume,
    store_uploaded_resume,
)


def test_job_profile_summarizes_skills_title_and_seniority() -> None:
    profile = job_profile(
        JobDescription(title="Senior Python Engineer", body="Python, AWS and Docker. 5+ years.")
    )
    assert "python" in profile["skills"]
    assert "aws" in profile["skills"]
    assert "senior" in profile["title_tokens"]
    assert profile["seniority"] == "senior"


def test_profile_similarity_high_for_similar_low_for_different() -> None:
    cloud = job_profile(
        JobDescription(title="Senior Cloud Engineer", body="AWS Kubernetes Terraform")
    )
    similar = job_profile(
        JobDescription(title="Cloud Engineer", body="AWS Kubernetes Terraform Docker")
    )
    different = job_profile(JobDescription(title="Pastry Chef", body="baking cakes and bread"))

    assert profile_similarity(cloud, similar) >= 0.3
    assert profile_similarity(cloud, different) < 0.3


def test_remember_and_load_round_trip(tmp_path) -> None:
    library = tmp_path / "library.json"
    resume = tmp_path / "cloud.txt"
    resume.write_text("AWS", encoding="utf-8")

    entry = remember_resume(
        library, JobDescription(title="Cloud Engineer", body="AWS"), str(resume)
    )

    assert entry["resume"] == str(resume)
    loaded = load_library(library)
    assert loaded and loaded[0]["resume"] == str(resume)
    assert loaded[0]["profile"]["skills"] == ["aws"]


def test_remember_replaces_an_existing_entry_for_the_same_resume(tmp_path) -> None:
    library = tmp_path / "library.json"
    resume = tmp_path / "cloud.txt"
    resume.write_text("AWS", encoding="utf-8")

    remember_resume(library, JobDescription(title="Cloud Engineer"), str(resume))
    remember_resume(library, JobDescription(title="Senior Cloud Engineer"), str(resume))

    entries = load_library(library)
    assert len(entries) == 1
    assert entries[0]["job_title"] == "Senior Cloud Engineer"


def test_find_reusable_resume_matches_a_similar_job(tmp_path) -> None:
    library = tmp_path / "library.json"
    resume = tmp_path / "cloud.txt"
    resume.write_text("AWS", encoding="utf-8")
    remember_resume(
        library,
        JobDescription(title="Senior Cloud Engineer", body="AWS Kubernetes Terraform"),
        str(resume),
    )
    entries = load_library(library)

    reusable = find_reusable_resume(
        entries,
        JobDescription(title="Cloud Engineer", body="AWS Kubernetes Terraform Docker"),
        tmp_path,
    )
    assert reusable == str(resume)


def test_find_reusable_resume_ignores_unrelated_and_missing(tmp_path) -> None:
    library = tmp_path / "library.json"
    resume = tmp_path / "cloud.txt"
    resume.write_text("AWS", encoding="utf-8")
    remember_resume(
        library, JobDescription(title="Cloud Engineer", body="AWS Kubernetes"), str(resume)
    )
    entries = load_library(library)

    assert (
        find_reusable_resume(
            entries, JobDescription(title="Pastry Chef", body="baking bread"), tmp_path
        )
        is None
    )

    resume.unlink()  # the remembered file is gone
    assert (
        find_reusable_resume(
            entries, JobDescription(title="Cloud Engineer", body="AWS Kubernetes"), tmp_path
        )
        is None
    )


def test_store_uploaded_resume_writes_and_never_overwrites(tmp_path) -> None:
    first = store_uploaded_resume(tmp_path, "resume.txt", b"first")
    second = store_uploaded_resume(tmp_path, "resume.txt", b"second")

    assert first.name == "resume.txt"
    assert first.read_bytes() == b"first"
    assert second.name == "resume (1).txt"
    assert second.read_bytes() == b"second"


def test_store_uploaded_resume_strips_directories(tmp_path) -> None:
    stored = store_uploaded_resume(tmp_path, "../evil/resume.md", b"hi")
    assert stored.parent == tmp_path
    assert stored.name == "resume.md"


def test_store_uploaded_resume_rejects_bad_input(tmp_path) -> None:
    with pytest.raises(ValueError):
        store_uploaded_resume(tmp_path, "resume.exe", b"x")
    with pytest.raises(ValueError):
        store_uploaded_resume(tmp_path, "resume.pdf", b"")
