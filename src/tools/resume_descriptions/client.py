"""Task 3.2's LLM calls: describe a resume, pick the best match.

The calls ask for JSON mode and, on OpenRouter, turn the model's hidden
reasoning **off** by default. Reasoning models otherwise spend hundreds to
thousands of tokens "thinking" before a two-line answer, which made resume
matching slow and — when the reasoning filled the output budget — returned an
empty ``content`` that read as "unusable reply". An unusable reply is retried
once with a stricter instruction; there is still no deterministic fallback.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path

from src.configuration import LLMSettings, Settings
from src.llm_model_routing import resume_llm_settings
from src.state import JobDescription

from .messages import (
    build_describe_messages,
    build_match_messages,
    candidate_ids,
    parse_description,
    parse_match,
)
from .models import ResumeDescription, ResumeDescriptionError, ResumeMatch

_JSON_ONLY_NUDGE = (
    "Your previous reply was not usable. Reply with ONE JSON object only. "
    "No prose, no code fence, no explanation."
)

_UNSUPPORTED_WORDS = (
    "unsupported",
    "not supported",
    "unknown",
    "unexpected",
    "invalid",
    "not permitted",
    "extra inputs",
)

# Provider/transport failures that are worth retrying. The OpenRouter API can
# surface a transient upstream outage as a plain "Connection error." response, and
# the OpenAI client's own retries do not cover every shape of it. A retry here is
# what keeps one network blip from stopping the resume match for the whole run.
_TRANSIENT_STATUS_CODES = frozenset({408, 409, 425, 429})
_TRANSIENT_NAMES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "ConnectionAbortedError",
        "ConnectionError",
        "ConnectionResetError",
        "InternalServerError",
        "PoolTimeout",
        "ReadError",
        "ReadTimeout",
        "RemoteProtocolError",
        "TimeoutError",
        "TimeoutException",
        "WriteError",
        "WriteTimeout",
    }
)
_TRANSIENT_MARKERS = (
    "connection error",
    "connection reset",
    "connection aborted",
    "connection refused",
    "connection closed",
    "server disconnected",
    "remote protocol",
    "temporarily unavailable",
    "network error",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "overloaded",
    "rate limit",
    "timed out",
    "timeout",
)


def _status_code(exc: Exception) -> int | None:
    """The HTTP status on ``exc`` (SDK or httpx style), when there is one."""
    code = getattr(exc, "status_code", None)
    if code is None:
        code = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        return int(code)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _is_transient_error(exc: Exception) -> bool:
    """True for a network/provider outage that a later attempt may clear."""
    code = _status_code(exc)
    if code is not None:
        return code in _TRANSIENT_STATUS_CODES or code >= 500
    if type(exc).__name__ in _TRANSIENT_NAMES:
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


async def _backoff_sleep(seconds: float) -> None:
    """Wait between transport retries (kept tiny and injectable for tests)."""
    if seconds > 0:
        await asyncio.sleep(seconds)


def _extract_text(path: str | Path) -> str:
    """Read a resume's text via Task 3's extractor (lazy: avoids an import cycle)."""
    from src.tools.linkedin_best_matching_resume import extract_resume_text

    return extract_resume_text(path)


def _build_client(settings: LLMSettings):
    from openai import AsyncOpenAI  # lazy: only needed when configured

    return AsyncOpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout=settings.timeout_seconds,
        max_retries=settings.max_retries,
    )


def _unsupported_param(exc: Exception, name: str) -> bool:
    """True when ``exc`` looks like the provider rejecting parameter ``name``."""
    text = str(exc).lower()
    return name in text and any(word in text for word in _UNSUPPORTED_WORDS)


def _looks_like_unknown_body_field(exc: Exception) -> bool:
    """True for a provider that rejects extra body fields without naming them."""
    text = str(exc).lower()
    return "extra inputs" in text or "extra fields" in text


def _request_kwargs(
    settings: LLMSettings, messages: list[dict[str, str]]
) -> dict:
    """The request body for one structured JSON call."""
    kwargs: dict = {
        "model": settings.model,
        "messages": messages,
        "temperature": settings.temperature,
        "response_format": {"type": "json_object"},
    }
    if getattr(settings, "disable_reasoning", True):
        # OpenRouter: skip hidden reasoning. Providers that do not know the key
        # are handled by the removal loop in :func:`_chat`.
        kwargs["extra_body"] = {"reasoning": {"enabled": False}}
    return kwargs


async def _chat_once(client, kwargs: dict) -> str:
    """Send one request, dropping provider-rejected knobs; return the reply text."""
    for _attempt in range(3):
        try:
            response = await client.chat.completions.create(**kwargs)
            break
        except Exception as exc:  # noqa: BLE001 - retry without an unsupported knob
            if "extra_body" in kwargs and (
                _unsupported_param(exc, "reasoning") or _looks_like_unknown_body_field(exc)
            ):
                kwargs.pop("extra_body")
                continue
            if "response_format" in kwargs and _unsupported_param(exc, "response_format"):
                kwargs.pop("response_format")
                continue
            raise
    else:  # pragma: no cover - the loop always breaks or raises
        return ""
    if not response.choices:
        return ""
    return response.choices[0].message.content or ""


async def _chat(client, settings: LLMSettings, messages: list[dict[str, str]]) -> str:
    """Send one chat request, retrying transient transport failures.

    A fresh request body is built for every attempt so a provider-rejected knob is
    removed again if needed. Deterministic failures and unusable replies are not
    retried here: the caller's JSON nudge handles the latter.
    """
    retries = max(0, int(getattr(settings, "transport_retries", 0) or 0))
    backoff = float(getattr(settings, "transport_retry_backoff_seconds", 0.0) or 0.0)
    for attempt in range(retries + 1):
        try:
            return await _chat_once(client, _request_kwargs(settings, messages))
        except Exception as exc:  # noqa: BLE001 - only transient errors are retried
            if attempt >= retries or not _is_transient_error(exc):
                raise
            await _backoff_sleep(backoff * (2**attempt))
    return ""  # pragma: no cover - the loop always returns or raises


async def _ask_json(client, settings: LLMSettings, messages: list[dict[str, str]], parse):
    """Ask once for JSON; retry once with a nudge when the reply is unusable."""
    reply = await _chat(client, settings, messages)
    try:
        return parse(reply)
    except ResumeDescriptionError:
        retry = [*messages]
        if reply.strip():
            retry.append({"role": "assistant", "content": reply})
        retry.append({"role": "user", "content": _JSON_ONLY_NUDGE})
        return parse(await _chat(client, settings, retry))


def _parsed_description(text: str) -> ResumeDescription:
    """Parse a description reply, raising when the model did not describe anything."""
    description = parse_description(text)
    if not description.usable:
        raise ResumeDescriptionError("the LLM returned an unusable resume description")
    return description


async def describe_resume(
    resume_path: str | Path,
    settings: Settings,
    *,
    client=None,
    extract_text: Callable[[str | Path], str] | None = None,
) -> ResumeDescription:
    """Describe one resume with the LLM, or raise (there is no fallback).

    Raises :class:`ResumeDescriptionError` when the LLM is not configured, the
    resume has no readable text, the call fails, or the reply is unusable.
    """
    llm = resume_llm_settings(settings)
    if not llm.configured:
        raise ResumeDescriptionError(
            "the resume LLM is not configured (set OPENROUTER_API_KEY and "
            "AUTOJOB_RESUME_LLM_MODEL or AUTOJOB_LLM_MODEL)"
        )
    text = (extract_text or _extract_text)(resume_path)
    if not text.strip():
        raise ResumeDescriptionError(f"no readable text in resume {resume_path}")

    client = client or _build_client(llm)
    messages = build_describe_messages(text)
    try:
        return await _ask_json(client, llm, messages, _parsed_description)
    except ResumeDescriptionError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface a clean Task 3.2 error
        raise ResumeDescriptionError(f"the LLM call failed: {exc}") from exc


async def pick_best_resume(
    job_description: JobDescription,
    candidates: Sequence[tuple[str, ResumeDescription]],
    settings: Settings,
    *,
    client=None,
) -> ResumeMatch:
    """Ask the LLM to choose the single best-matching resume, or none.

    An empty candidate list is a no-match without an LLM call. Raises
    :class:`ResumeDescriptionError` when the LLM is not configured or the call fails;
    a **none** answer or an unknown id is returned as a no-match.
    """
    if not candidates:
        return ResumeMatch()
    llm = resume_llm_settings(settings)
    if not llm.configured:
        raise ResumeDescriptionError(
            "the resume LLM is not configured (set OPENROUTER_API_KEY and "
            "AUTOJOB_RESUME_LLM_MODEL or AUTOJOB_LLM_MODEL)"
        )

    ids = candidate_ids(candidates)
    client = client or _build_client(llm)
    messages = build_match_messages(job_description, candidates, ids)
    try:
        return await _ask_json(
            client, llm, messages, lambda reply: parse_match(reply, ids)
        )
    except ResumeDescriptionError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface a clean Task 3.2 error
        raise ResumeDescriptionError(f"the LLM call failed: {exc}") from exc


__all__ = [
    "describe_resume",
    "pick_best_resume",
]
