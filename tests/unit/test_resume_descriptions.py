"""Unit tests for Task 3.2's LLM resume descriptions + match (no network)."""

from __future__ import annotations

import pytest

from src.configuration import LLMSettings, Settings
from src.state import JobDescription
from src.tools.resume_descriptions import (
    ResumeDescription,
    ResumeDescriptionError,
    build_describe_messages,
    build_match_messages,
    candidate_ids,
    canonical_path,
    describe_resume,
    described_candidates,
    description_for,
    ensure_descriptions,
    is_fresh,
    load_descriptions,
    parse_description,
    parse_match,
    pick_best_resume,
    store_description,
)


def _settings(tmp_path, **llm) -> Settings:
    return Settings(
        llm=LLMSettings(**llm),
        data_dir=tmp_path,
        resume_descriptions_path=tmp_path / "resume_descriptions.json",
    )


class _FakeClient:
    """A minimal stand-in for ``AsyncOpenAI`` that records the call."""

    def __init__(self, content: str = "", *, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.calls: list[dict] = []
        self.chat = self
        self.completions = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return _FakeResponse(self.content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


# --- the store --------------------------------------------------------------


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


# --- parsing the description reply -----------------------------------------


def test_parse_description_reads_and_normalises_fields() -> None:
    text = (
        '{"summary": "Backend engineer", "skills": ["Python", "python", " AWS "], '
        '"titles": ["Senior Engineer"], "seniority": "Senior", '
        '"years_experience": "8+", "domain": "fintech"}'
    )
    description = parse_description(text)

    assert description.summary == "Backend engineer"
    assert description.skills == ["Python", "AWS"]
    assert description.titles == ["Senior Engineer"]
    assert description.seniority == "senior"
    assert description.years_experience == 8
    assert description.domain == "fintech"


def test_parse_description_survives_prose_and_fences() -> None:
    text = 'Sure!\n```json\n{"summary": "x", "skills": "Python, AWS"}\n```'
    description = parse_description(text)
    assert description.summary == "x"
    assert description.skills == ["Python", "AWS"]


def test_parse_description_handles_bad_json() -> None:
    assert parse_description("not json").usable is False
    assert parse_description("").usable is False
    assert parse_description('{"unterminated": ').usable is False


# --- describing a resume ----------------------------------------------------


async def test_describe_resume_requires_a_configured_llm(tmp_path) -> None:
    resume = tmp_path / "r.txt"
    resume.write_text("Python", encoding="utf-8")

    with pytest.raises(ResumeDescriptionError):
        await describe_resume(resume, _settings(tmp_path))


async def test_describe_resume_rejects_unreadable_text(tmp_path) -> None:
    resume = tmp_path / "r.txt"
    resume.write_text("   ", encoding="utf-8")

    with pytest.raises(ResumeDescriptionError):
        await describe_resume(
            resume, _settings(tmp_path, api_key="k", model="m"), client=_FakeClient("{}")
        )


async def test_describe_resume_returns_the_llm_description(tmp_path) -> None:
    resume = tmp_path / "r.txt"
    resume.write_text("Python, AWS, 8 years", encoding="utf-8")
    fake = _FakeClient('{"summary": "Backend", "skills": ["Python"], "years_experience": 8}')

    description = await describe_resume(
        resume, _settings(tmp_path, api_key="k", model="m"), client=fake
    )

    assert description.summary == "Backend"
    assert description.skills == ["Python"]
    assert description.years_experience == 8
    assert fake.calls[0]["model"] == "m"


async def test_describe_resume_raises_on_a_call_error(tmp_path) -> None:
    resume = tmp_path / "r.txt"
    resume.write_text("Python", encoding="utf-8")

    with pytest.raises(ResumeDescriptionError):
        await describe_resume(
            resume,
            _settings(tmp_path, api_key="k", model="m"),
            client=_FakeClient(error=RuntimeError("boom")),
        )


async def test_describe_resume_raises_on_an_unusable_reply(tmp_path) -> None:
    resume = tmp_path / "r.txt"
    resume.write_text("Python", encoding="utf-8")

    with pytest.raises(ResumeDescriptionError):
        await describe_resume(
            resume, _settings(tmp_path, api_key="k", model="m"), client=_FakeClient("no json")
        )


def test_build_describe_messages_include_the_resume_text() -> None:
    messages = build_describe_messages("Python, AWS")
    assert messages[0]["role"] == "system"
    assert "Python, AWS" in messages[1]["content"]


# --- picking the best match -------------------------------------------------


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
    match = parse_match('{"choice": "c2", "rationale": "best fit"}', ids)

    assert match.selected_path == "b.pdf"
    assert match.rationale == "best fit"
    assert match.candidate_ids == ids


def test_parse_match_none_or_unknown_id_is_a_no_match() -> None:
    ids = {"c1": "a.pdf"}
    assert parse_match('{"choice": "none"}', ids).selected_path is None
    assert parse_match('{"choice": "c9"}', ids).selected_path is None
    assert parse_match('{"choice": ""}', ids).selected_path is None


def test_parse_match_rejects_an_unusable_reply() -> None:
    with pytest.raises(ResumeDescriptionError):
        parse_match("not json at all", {"c1": "a.pdf"})


async def test_pick_best_resume_returns_the_choice(tmp_path) -> None:
    fake = _FakeClient('{"choice": "c1", "rationale": "r"}')

    match = await pick_best_resume(
        JobDescription(title="X", body="Y"),
        [("a.pdf", ResumeDescription(summary="s"))],
        _settings(tmp_path, api_key="k", model="m"),
        client=fake,
    )

    assert match.selected_path == "a.pdf"
    assert fake.calls[0]["model"] == "m"


async def test_pick_best_resume_requires_a_configured_llm(tmp_path) -> None:
    with pytest.raises(ResumeDescriptionError):
        await pick_best_resume(
            JobDescription(title="X"),
            [("a.pdf", ResumeDescription(summary="s"))],
            _settings(tmp_path),
        )


async def test_pick_best_resume_without_candidates_is_a_no_match(tmp_path) -> None:
    match = await pick_best_resume(JobDescription(title="X"), [], _settings(tmp_path))
    assert match.selected_path is None


async def test_pick_best_resume_raises_on_a_call_error(tmp_path) -> None:
    with pytest.raises(ResumeDescriptionError):
        await pick_best_resume(
            JobDescription(title="X"),
            [("a.pdf", ResumeDescription(summary="s"))],
            _settings(tmp_path, api_key="k", model="m"),
            client=_FakeClient(error=RuntimeError("boom")),
        )


# --- ensuring the whole pool is described -----------------------------------


async def test_ensure_descriptions_describes_new_and_reuses_fresh(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("Python", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Java", encoding="utf-8")
    store = tmp_path / "resume_descriptions.json"
    settings = _settings(tmp_path, api_key="k", model="m")
    fake = _FakeClient('{"summary": "s", "skills": ["x"]}')

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
    settings = _settings(tmp_path, api_key="k", model="m")
    fake = _FakeClient('{"summary": "s"}')

    await ensure_descriptions(tmp_path, store, settings, client=fake)
    calls_after_first = len(fake.calls)

    resume.write_text("Python and AWS", encoding="utf-8")  # changed
    await ensure_descriptions(tmp_path, store, settings, client=fake)

    assert len(fake.calls) == calls_after_first + 1
