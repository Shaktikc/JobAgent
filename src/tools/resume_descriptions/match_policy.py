"""Task 16 eligibility: prefer strong ratings, then allow partial ratings."""

from __future__ import annotations

from collections.abc import Mapping

ELIGIBLE_FITS = ("strong", "partial")


def is_eligible_fit(fit: str) -> bool:
    """Accept only a normalized strong or partial LLM rating."""
    return fit in ELIGIBLE_FITS


def choose_rated_candidate(choice: str | None, ratings: Mapping[str, str]) -> str | None:
    """Use the LLM's best eligible rating, retaining its choice within that tier.

    The caller filters out ids that were not supplied to the model. Rating order
    is the model's preference order when its single choice is not in the best
    tier. No keyword scoring or inferred fit is involved.
    """
    for fit in ELIGIBLE_FITS:
        if choice is not None and ratings.get(choice) == fit:
            return choice
        for candidate, rating in ratings.items():
            if rating == fit:
                return candidate
    return None
