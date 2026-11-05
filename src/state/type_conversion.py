"""Metadata-only audit of rejected-answer type repairs; never persist values."""

from typing import Literal

from pydantic import BaseModel


class TypeConversionAttempt(BaseModel):
    question: str = ""
    direction: Literal["text_to_number", "number_to_text"]
    attempted: bool = False
    outcome: Literal[
        "not_possible",
        "entered",
        "accepted",
        "rejected",
        "not_retried",
        "entry_failed",
    ] = "not_possible"
