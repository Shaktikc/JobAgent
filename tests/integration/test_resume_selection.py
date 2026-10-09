"""Opt-in integration test that picks a resume from the real ``resumes/`` folder.

It exercises the real PDF extractor (``pypdf``) against the resumes actually
present in the repository, so it only runs when the folder is populated:

    uv run pytest tests/integration

Skipped by default when ``resumes/`` is empty or missing.
"""

from __future__ import annotations

import pytest

from src.configuration import load_settings
from src.state import JobDescription
from src.tools.linkedin_best_matching_resume import list_resume_files, select_best_resume

RESUMES_DIR = load_settings().resumes_dir
RESUME_FILES = list_resume_files(RESUMES_DIR)

pytestmark = pytest.mark.skipif(
    not RESUME_FILES,
    reason="populate resumes/ to run the resume-selection integration test",
)


def test_every_resume_is_read_and_exactly_one_is_selected() -> None:
    description = JobDescription(
        title="Senior Python Backend Engineer",
        body="Python, AWS, Docker and PostgreSQL. 5+ years required.",
    )

    outcome = select_best_resume(description, RESUMES_DIR)

    assert outcome.resumes_found == len(RESUME_FILES)
    assert len(outcome.candidates) == len(RESUME_FILES)
    assert outcome.selected_path is not None
    assert outcome.rationale
    # The chosen resume is one of the files actually on disk.
    assert outcome.selected_path in {str(path) for path in RESUME_FILES}
