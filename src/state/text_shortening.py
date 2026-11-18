"""Metadata-only character-limit repair audit."""

from pydantic import BaseModel


class TextShorteningAttempt(BaseModel):
    question: str = ""
    limit: int = 0
    original_length: int = 0
    shortened_length: int = 0
    attempted: bool = False
    outcome: str = "not_possible"
