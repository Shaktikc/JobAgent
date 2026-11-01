"""The pick-best-resume LLM call and its request/retry behaviour."""

from __future__ import annotations

import pytest

from src.state import JobDescription
from src.tools.resume_descriptions import (
    ResumeDescription,
    ResumeDescriptionError,
    describe_resume,
    pick_best_resume,
)

from .helpers import FakeClient, make_settings

_MATCH_REPLY = '{"choice":"c1","ratings":{"c1":"strong"},"rationale":"r"}'


async def test_pick_best_resume_returns_the_choice(tmp_path) -> None:
    fake = FakeClient(_MATCH_REPLY)

    match = await pick_best_resume(
        JobDescription(title="X", body="Y"),
        [("a.pdf", ResumeDescription(summary="s"))],
        make_settings(tmp_path, api_key="k", model="m"),
        client=fake,
    )

    assert match.selected_path == "a.pdf"
    assert fake.calls[0]["model"] == "m"


async def test_resume_calls_use_the_general_model_even_with_self_heal_set(
    tmp_path, monkeypatch
) -> None:
    """Task 14: the general model drives both resume calls, never the repair model."""
    monkeypatch.setenv(
        "AUTOJOB_SELF_HEAL_REPAIR_MODEL", "deepseek/deepseek-v4.1-flash-1017"
    )
    settings = make_settings(tmp_path, api_key="k", model="xiaomi/mimo-v2.6-pro")

    resume = tmp_path / "r.txt"
    resume.write_text("Python, AWS, 8 years", encoding="utf-8")
    describe_fake = FakeClient('{"summary": "Backend", "skills": ["Python"]}')
    await describe_resume(resume, settings, client=describe_fake)
    assert describe_fake.calls[0]["model"] == settings.llm.model == "xiaomi/mimo-v2.6-pro"

    match_fake = FakeClient(_MATCH_REPLY)
    await pick_best_resume(
        JobDescription(title="X", body="Y"),
        [("a.pdf", ResumeDescription(summary="s"))],
        settings,
        client=match_fake,
    )
    assert match_fake.calls[0]["model"] == settings.llm.model


async def test_pick_best_resume_requires_a_configured_llm(tmp_path) -> None:
    with pytest.raises(ResumeDescriptionError):
        await pick_best_resume(
            JobDescription(title="X"),
            [("a.pdf", ResumeDescription(summary="s"))],
            make_settings(tmp_path),
        )


async def test_pick_best_resume_without_candidates_is_a_no_match(tmp_path) -> None:
    match = await pick_best_resume(
        JobDescription(title="X"), [], make_settings(tmp_path)
    )
    assert match.selected_path is None


async def test_pick_best_resume_raises_on_a_call_error(tmp_path) -> None:
    with pytest.raises(ResumeDescriptionError):
        await pick_best_resume(
            JobDescription(title="X"),
            [("a.pdf", ResumeDescription(summary="s"))],
            make_settings(tmp_path, api_key="k", model="m"),
            client=FakeClient(error=RuntimeError("boom")),
        )


async def test_pick_best_resume_requests_json_and_no_reasoning(tmp_path) -> None:
    fake = FakeClient(_MATCH_REPLY)

    await pick_best_resume(
        JobDescription(title="X", body="Y"),
        [("a.pdf", ResumeDescription(summary="s"))],
        make_settings(tmp_path, api_key="k", model="m"),
        client=fake,
    )

    call = fake.calls[0]
    assert call["response_format"] == {"type": "json_object"}
    assert call["extra_body"] == {"reasoning": {"enabled": False}}


async def test_pick_best_resume_retries_an_empty_reply(tmp_path) -> None:
    # A reasoning model can return finish_reason=length with empty content; the
    # match retries once instead of failing the whole job.
    fake = FakeClient(["", _MATCH_REPLY])

    match = await pick_best_resume(
        JobDescription(title="X", body="Y"),
        [("a.pdf", ResumeDescription(summary="s"))],
        make_settings(tmp_path, api_key="k", model="m"),
        client=fake,
    )

    assert match.selected_path == "a.pdf"
    assert len(fake.calls) == 2


async def test_pick_best_resume_retries_a_transient_connection_error(tmp_path) -> None:
    """BUG-080: one provider "Connection error." must not abort the whole match."""
    fake = FakeClient(
        _MATCH_REPLY,
        errors=[RuntimeError("Connection error."), None],
    )

    match = await pick_best_resume(
        JobDescription(title="X", body="Y"),
        [("a.pdf", ResumeDescription(summary="s"))],
        make_settings(
            tmp_path,
            api_key="k",
            model="m",
            transport_retry_backoff_seconds=0,
        ),
        client=fake,
    )

    assert match.selected_path == "a.pdf"
    assert len(fake.calls) == 2


async def test_pick_best_resume_retries_an_upstream_5xx(tmp_path) -> None:
    class UpstreamUnavailable(RuntimeError):
        status_code = 503

    fake = FakeClient(
        _MATCH_REPLY,
        errors=[UpstreamUnavailable("provider unavailable"), None],
    )

    match = await pick_best_resume(
        JobDescription(title="X", body="Y"),
        [("a.pdf", ResumeDescription(summary="s"))],
        make_settings(
            tmp_path,
            api_key="k",
            model="m",
            transport_retry_backoff_seconds=0,
        ),
        client=fake,
    )

    assert match.selected_path == "a.pdf"
    assert len(fake.calls) == 2


async def test_pick_best_resume_does_not_retry_a_deterministic_error(tmp_path) -> None:
    fake = FakeClient(error=RuntimeError("invalid api key"))

    with pytest.raises(ResumeDescriptionError):
        await pick_best_resume(
            JobDescription(title="X", body="Y"),
            [("a.pdf", ResumeDescription(summary="s"))],
            make_settings(
                tmp_path,
                api_key="k",
                model="m",
                transport_retry_backoff_seconds=0,
            ),
            client=fake,
        )

    assert len(fake.calls) == 1
