"""Task 3.2 data models: a resume profile, a match result, and the error type.

Kept separate from the store and the LLM client so both can import the models
without pulling in the network stack.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .match_policy import is_eligible_fit


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
    # Task 3.2: factual evidence the matcher can reason over. A one-line summary
    # plus a skill list drops the leadership/architecture/platform work that
    # senior roles are judged on, which caused false "partial" ratings.
    highlights: list[str] = Field(default_factory=list)
    # The AI coding assistants/agents the resume names (Claude Code, Cursor,
    # Copilot, ...). This is a common core requirement, so it is captured
    # explicitly instead of being buried in the general skill list.
    ai_coding_tools: list[str] = Field(default_factory=list)

    @property
    def usable(self) -> bool:
        """True when the reply actually described the resume (not empty)."""
        return bool(
            self.summary.strip()
            or self.skills
            or self.titles
            or self.domain.strip()
            or self.highlights
            or self.ai_coding_tools
        )


class ResumeMatch(BaseModel):
    """The LLM's choice of the single best-matching resume (Task 3.2).

    ``selected_path`` is ``None`` when the model answered **none** or named an id
    that is not one of the candidates; ``candidate_ids`` records the id -> path
    map so the decision stays explainable. Task 16 adds ``fit``: the model's
    quality rating for the chosen resume (``"strong"``, ``"partial"``, ``"none"``,
    or ``""`` when it did not say). Strong and partial matches may proceed to
    Easy Apply; strong candidates are preferred.

    ``ratings`` records the model's per-candidate ratings (id -> fit). A model can
    name a thematically closer but weaker candidate as its single ``choice`` while
    rating another candidate strong; the gate uses these ratings so a strong
    candidate is not skipped just because the single choice was partial.
    """

    selected_path: str | None = None
    fit: str = ""
    rationale: str = ""
    candidate_ids: dict[str, str] = Field(default_factory=dict)
    ratings: dict[str, str] = Field(default_factory=dict)

    @property
    def is_strong(self) -> bool:
        """True when a resume was chosen and the LLM rated it a strong fit."""
        return bool(self.selected_path and self.fit == "strong")

    @property
    def is_eligible(self) -> bool:
        """True when a selected resume has a strong or partial resolved rating."""
        return bool(self.selected_path and is_eligible_fit(self.fit))


class ResumeDescriptionError(RuntimeError):
    """Task 3.2 could not describe or match (there is no deterministic fallback)."""


__all__ = [
    "ResumeDescription",
    "ResumeDescriptionError",
    "ResumeMatch",
]
