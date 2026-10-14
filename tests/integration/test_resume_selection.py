"""Opt-in live test that picks a resume from the real ``resumes/`` folder.

It exercises the real PDF extractor (``pypdf``) and a real LLM call against the
resumes actually present in the repository. Because it needs the network and a
configured LLM, it is gated behind an explicit opt-in variable:

    AUTOJOB_RESUME_LIVE=1 uv run pytest tests/integration/test_resume_selection.py -s

Skipped unless ``AUTOJOB_RESUME_LIVE`` is set, ``resumes/`` is populated, and the
LLM is configured (``OPENROUTER_API_KEY`` + ``AUTOJOB_LLM_MODEL``).
"""

from __future__ import annotations

import os

import pytest

from src.configuration import load_settings
from src.state import JobDescription
from src.tools.linkedin_best_matching_resume import list_resume_files
from src.tools.resume_descriptions import (
    described_candidates,
    ensure_descriptions,
    load_descriptions,
    pick_best_resume,
)

SETTINGS = load_settings()
RESUME_FILES = list_resume_files(SETTINGS.resumes_dir)

pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTOJOB_RESUME_LIVE") or not RESUME_FILES or not SETTINGS.llm.configured,
    reason=(
        "set AUTOJOB_RESUME_LIVE=1, populate resumes/, and configure the LLM "
        "(OPENROUTER_API_KEY + AUTOJOB_LLM_MODEL) to run this live test"
    ),
)


async def test_every_resume_is_described_and_at_most_one_is_picked() -> None:
    description = JobDescription(
        title="Senior Python Backend Engineer",
        body="Python, AWS, Docker and PostgreSQL. 5+ years required.",
    )

    await ensure_descriptions(
        SETTINGS.resumes_dir, SETTINGS.resume_descriptions_file, SETTINGS, files=RESUME_FILES
    )
    candidates = described_candidates(
        RESUME_FILES, load_descriptions(SETTINGS.resume_descriptions_file)
    )
    assert len(candidates) == len(RESUME_FILES)

    match = await pick_best_resume(description, candidates, SETTINGS)

    if match.selected_path is not None:
        # The chosen resume is one of the files actually on disk.
        assert match.selected_path in {str(path) for path in RESUME_FILES}
        assert match.rationale
