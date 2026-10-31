"""Shared helpers for Task 3.2's resume-description tests."""

from __future__ import annotations

from src.configuration import LLMSettings, Settings


def make_settings(tmp_path, **llm) -> Settings:
    """Settings with a temp description store and optional LLM overrides."""
    return Settings(
        llm=LLMSettings(**llm),
        data_dir=tmp_path,
        resume_descriptions_path=tmp_path / "resume_descriptions.json",
    )


class FakeClient:
    """A minimal stand-in for ``AsyncOpenAI`` that records each call."""

    def __init__(
        self,
        content: str | list[str] = "",
        *,
        error: Exception | None = None,
        errors: list[Exception | None] | None = None,
    ) -> None:
        self.contents = list(content) if isinstance(content, list) else [content]
        if errors is not None:
            # Per-call outcomes: an exception raises, ``None`` falls through to
            # the normal content. Used to prove a transient failure is retried.
            self.errors = list(errors)
        else:
            self.errors = [error] if error is not None else []
        self.calls: list[dict] = []
        self.chat = self
        self.completions = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.errors:
            failure = self.errors.pop(0)
            if failure is not None:
                raise failure
        content = self.contents.pop(0) if len(self.contents) > 1 else self.contents[0]
        return FakeResponse(content)


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [FakeChoice(content)]


class FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = FakeMessage(content)


class FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content
