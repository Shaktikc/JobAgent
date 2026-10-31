"""Parsing a description reply and the per-resume LLM call."""

from __future__ import annotations

import pytest

from src.tools.resume_descriptions import (
    ResumeDescriptionError,
    build_describe_messages,
    describe_resume,
    parse_description,
)

from .helpers import FakeClient, make_settings


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


def test_parse_description_reads_highlights_and_ai_coding_tools() -> None:
    text = (
        '{"summary": "Senior engineer", '
        '"highlights": ["Led a four-person team", "Built an internal platform", ""], '
        '"ai_coding_tools": ["Claude Code", "Cursor", "cursor"]}'
    )
    description = parse_description(text)

    assert description.highlights == ["Led a four-person team", "Built an internal platform"]
    assert description.ai_coding_tools == ["Claude Code", "Cursor"]


def test_parse_description_survives_prose_and_fences() -> None:
    text = 'Sure!\n```json\n{"summary": "x", "skills": "Python, AWS"}\n```'
    description = parse_description(text)
    assert description.summary == "x"
    assert description.skills == ["Python", "AWS"]


def test_parse_description_handles_bad_json() -> None:
    assert parse_description("not json").usable is False
    assert parse_description("").usable is False
    assert parse_description('{"unterminated": ').usable is False


async def test_describe_resume_requires_a_configured_llm(tmp_path) -> None:
    resume = tmp_path / "r.txt"
    resume.write_text("Python", encoding="utf-8")

    with pytest.raises(ResumeDescriptionError):
        await describe_resume(resume, make_settings(tmp_path))


async def test_describe_resume_rejects_unreadable_text(tmp_path) -> None:
    resume = tmp_path / "r.txt"
    resume.write_text("   ", encoding="utf-8")

    with pytest.raises(ResumeDescriptionError):
        await describe_resume(
            resume,
            make_settings(tmp_path, api_key="k", model="m"),
            client=FakeClient("{}"),
        )


async def test_describe_resume_returns_the_llm_description(tmp_path) -> None:
    resume = tmp_path / "r.txt"
    resume.write_text("Python, AWS, 8 years", encoding="utf-8")
    fake = FakeClient('{"summary": "Backend", "skills": ["Python"], "years_experience": 8}')

    description = await describe_resume(
        resume, make_settings(tmp_path, api_key="k", model="m"), client=fake
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
            make_settings(tmp_path, api_key="k", model="m"),
            client=FakeClient(error=RuntimeError("boom")),
        )


async def test_describe_resume_retries_a_transient_connection_error(tmp_path) -> None:
    """BUG-080: describing the pool survives a transient provider error too."""
    resume = tmp_path / "r.txt"
    resume.write_text("Python", encoding="utf-8")
    fake = FakeClient(
        '{"summary": "Backend"}',
        errors=[RuntimeError("Connection error."), None],
    )

    description = await describe_resume(
        resume,
        make_settings(
            tmp_path,
            api_key="k",
            model="m",
            transport_retry_backoff_seconds=0,
        ),
        client=fake,
    )

    assert description.summary == "Backend"
    assert len(fake.calls) == 2


async def test_describe_resume_raises_on_an_unusable_reply(tmp_path) -> None:
    resume = tmp_path / "r.txt"
    resume.write_text("Python", encoding="utf-8")

    with pytest.raises(ResumeDescriptionError):
        await describe_resume(
            resume,
            make_settings(tmp_path, api_key="k", model="m"),
            client=FakeClient("no json"),
        )


async def test_describe_resume_retries_an_unusable_reply(tmp_path) -> None:
    resume = tmp_path / "r.txt"
    resume.write_text("Python", encoding="utf-8")
    fake = FakeClient(["not json", '{"summary": "Backend"}'])

    description = await describe_resume(
        resume, make_settings(tmp_path, api_key="k", model="m"), client=fake
    )

    assert description.summary == "Backend"
    assert len(fake.calls) == 2


def test_build_describe_messages_include_the_resume_text() -> None:
    messages = build_describe_messages("Python, AWS")
    assert messages[0]["role"] == "system"
    assert "Python, AWS" in messages[1]["content"]
