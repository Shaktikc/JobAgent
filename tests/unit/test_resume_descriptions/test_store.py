"""The Task 3.2 description store and the pool-wide describe step."""

from __future__ import annotations

import json

import pytest

from src.tools.resume_descriptions import (
    PROFILE_VERSION,
    ResumeDescription,
    ResumeDescriptionError,
    canonical_path,
    described_candidates,
    description_for,
    ensure_descriptions,
    is_fresh,
    load_descriptions,
    store_description,
)

from .helpers import FakeClient, make_settings


def test_store_and_reload_description(tmp_path) -> None:
    resume = tmp_path / "cloud.txt"
    resume.write_text("AWS", encoding="utf-8")
    store = tmp_path / "resume_descriptions.json"
    description = ResumeDescription(
        summary="Cloud engineer",
        skills=["AWS"],
        titles=["Cloud Engineer"],
        seniority="senior",
        years_experience=8,
        domain="cloud",
    )

    entry = store_description(store, resume, description)

    assert entry["size"] == 3
    assert entry["profile_version"] == PROFILE_VERSION
    entries = load_descriptions(store)
    assert canonical_path(resume) in entries
    assert description_for(entries, resume) == description


def test_store_description_updates_the_same_entry(tmp_path) -> None:
    resume = tmp_path / "cloud.txt"
    resume.write_text("AWS", encoding="utf-8")
    store = tmp_path / "resume_descriptions.json"

    store_description(store, resume, ResumeDescription(summary="one"))
    store_description(store, resume, ResumeDescription(summary="two"))

    entries = load_descriptions(store)
    assert len(entries) == 1
    assert description_for(entries, resume).summary == "two"


def test_description_for_missing_resume_is_none(tmp_path) -> None:
    assert description_for({}, tmp_path / "nope.txt") is None


def test_described_candidates_requires_a_description(tmp_path) -> None:
    resume = tmp_path / "a.txt"
    resume.write_text("Python", encoding="utf-8")
    store = tmp_path / "resume_descriptions.json"
    store_description(store, resume, ResumeDescription(summary="s"))
    entries = load_descriptions(store)

    candidates = described_candidates([resume], entries)
    assert candidates[0][0] == str(resume)
    assert candidates[0][1].summary == "s"

    with pytest.raises(ResumeDescriptionError):
        described_candidates([tmp_path / "missing.txt"], entries)


def test_is_fresh_tracks_the_file(tmp_path) -> None:
    resume = tmp_path / "r.txt"
    resume.write_text("hello", encoding="utf-8")
    store = tmp_path / "resume_descriptions.json"
    store_description(store, resume, ResumeDescription(summary="s"))
    entry = load_descriptions(store)[canonical_path(resume)]

    assert is_fresh(entry, resume) is True

    resume.write_text("hello world", encoding="utf-8")  # size changed
    assert is_fresh(entry, resume) is False
    assert is_fresh(entry, tmp_path / "missing.txt") is False


def test_is_fresh_rejects_an_old_profile_version(tmp_path) -> None:
    resume = tmp_path / "r.txt"
    resume.write_text("hello", encoding="utf-8")
    store = tmp_path / "resume_descriptions.json"
    store_description(store, resume, ResumeDescription(summary="s"))
    entry = load_descriptions(store)[canonical_path(resume)]

    assert entry["profile_version"] == PROFILE_VERSION
    entry.pop("profile_version")
    assert is_fresh(entry, resume) is False


async def test_ensure_descriptions_describes_new_and_reuses_fresh(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("Python", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Java", encoding="utf-8")
    store = tmp_path / "resume_descriptions.json"
    settings = make_settings(tmp_path, api_key="k", model="m")
    fake = FakeClient('{"summary": "s", "skills": ["x"]}')

    first = await ensure_descriptions(tmp_path, store, settings, client=fake)
    assert len(first) == 2
    calls_after_first = len(fake.calls)
    assert calls_after_first == 2

    second = await ensure_descriptions(tmp_path, store, settings, client=fake)
    assert second == first
    assert len(fake.calls) == calls_after_first  # reused, no new LLM calls


async def test_ensure_descriptions_redescribes_a_changed_resume(tmp_path) -> None:
    resume = tmp_path / "a.txt"
    resume.write_text("Python", encoding="utf-8")
    store = tmp_path / "resume_descriptions.json"
    settings = make_settings(tmp_path, api_key="k", model="m")
    fake = FakeClient('{"summary": "s"}')

    await ensure_descriptions(tmp_path, store, settings, client=fake)
    calls_after_first = len(fake.calls)

    resume.write_text("Python and AWS", encoding="utf-8")  # changed
    await ensure_descriptions(tmp_path, store, settings, client=fake)

    assert len(fake.calls) == calls_after_first + 1


async def test_ensure_descriptions_redescribes_an_old_profile_version(tmp_path) -> None:
    resume = tmp_path / "a.txt"
    resume.write_text("Python", encoding="utf-8")
    store = tmp_path / "resume_descriptions.json"
    settings = make_settings(tmp_path, api_key="k", model="m")
    store_description(store, resume, ResumeDescription(summary="old"))
    entries = load_descriptions(store)
    old = entries[canonical_path(resume)]
    old["profile_version"] = PROFILE_VERSION - 1
    store.write_text(json.dumps({canonical_path(resume): old}), encoding="utf-8")

    fake = FakeClient('{"summary": "new", "highlights": ["Led a team"]}')
    await ensure_descriptions(tmp_path, store, settings, client=fake)

    assert len(fake.calls) == 1
    refreshed = load_descriptions(store)[canonical_path(resume)]
    assert refreshed["summary"] == "new"
    assert refreshed["highlights"] == ["Led a team"]
    assert refreshed["profile_version"] == PROFILE_VERSION
