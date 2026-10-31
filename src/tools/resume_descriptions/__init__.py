"""Task 3.2: LLM-written resume descriptions and the LLM resume match.

Kept a short, LLM-written profile for every resume in the pool
(``data/resume_descriptions.json``, keyed by the resume's canonical path) and has
the **LLM** choose the best-matching resume for a job directly from those
descriptions. There is **no deterministic fallback** anywhere in this package: if
the LLM is not configured, the call fails, or the reply is unusable, an error is
raised and the run stops instead of scoring another way.

The package is split by concern: :mod:`.models`, :mod:`.messages`, :mod:`.store`,
and :mod:`.client`. This module re-exports the public API so existing imports keep
working unchanged. It never touches the browser and never modifies a resume file
(only the sidecar store changes).
"""

from __future__ import annotations

from .client import describe_resume, pick_best_resume
from .messages import (
    build_describe_messages,
    build_match_messages,
    candidate_ids,
    parse_description,
    parse_match,
)
from .models import ResumeDescription, ResumeDescriptionError, ResumeMatch
from .store import (
    PROFILE_VERSION,
    canonical_path,
    described_candidates,
    description_for,
    ensure_descriptions,
    is_fresh,
    load_descriptions,
    move_description,
    save_descriptions,
    store_description,
)

__all__ = [
    "PROFILE_VERSION",
    "ResumeDescription",
    "ResumeDescriptionError",
    "ResumeMatch",
    "build_describe_messages",
    "build_match_messages",
    "candidate_ids",
    "canonical_path",
    "describe_resume",
    "described_candidates",
    "description_for",
    "ensure_descriptions",
    "is_fresh",
    "load_descriptions",
    "move_description",
    "parse_description",
    "parse_match",
    "pick_best_resume",
    "save_descriptions",
    "store_description",
]
