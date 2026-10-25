"""Task 3.2 data models: a resume profile, a match result, and the error type.

Kept separate from the store and the LLM client so both can import the models
without pulling in the network stack.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResumeDescription(BaseModel):
    """A short, LLM-written profile of one resume (Task 3.2).

    The model only ever summarises what the resume states; a missing field is left
    empty rather than guessed.
    """

    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    seniority: str = ""
    years_experience: int | None = None
    domain: str = ""

    @property
    def usable(self) -> bool:
        """True when the reply actually described the resume (not empty)."""
        return bool(self.summary.strip() or self.skills or self.titles or self.domain.strip())


class ResumeMatch(BaseModel):
    """The LLM's choice of the single best-matching resume (Task 3.2).

    ``selected_path`` is ``None`` when the model answered **none** or named an id
    that is not one of the candidates; ``candidate_ids`` records the id -> path
    map so the decision stays explainable.
    """

    selected_path: str | None = None
    rationale: str = ""
    candidate_ids: dict[str, str] = Field(default_factory=dict)


class ResumeDescriptionError(RuntimeError):
    """Task 3.2 could not describe or match (there is no deterministic fallback)."""


__all__ = [
    "ResumeDescription",
    "ResumeDescriptionError",
    "ResumeMatch",
]
