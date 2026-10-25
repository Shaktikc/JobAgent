"""Task 3: read the open job's description and pick the best-matching resume.

The package is split by concern:

- :mod:`.description_reader` — the deterministic CDP read of the open job.
- :mod:`.resume_text` — resume discovery and text extraction (read-only).
- :mod:`.resume_prompt` — the Task 3.1 browser banner that asks the human.
- :mod:`.selection` — the Task 3 flow that ties 3.1 and 3.2 together.

This module re-exports the public API so existing imports keep working unchanged.
"""

from __future__ import annotations

from .description_reader import _JOB_DESCRIPTION_QUERY, read_job_description
from .resume_prompt import DEFAULT_RESUME_PROMPT, ask_human_for_resume
from .resume_text import (
    RESUME_SUFFIXES,
    _extract_docx,
    _extract_pdf,
    extract_resume_text,
    list_resume_files,
)
from .selection import ensure_resume

__all__ = [
    "DEFAULT_RESUME_PROMPT",
    "RESUME_SUFFIXES",
    "_JOB_DESCRIPTION_QUERY",
    "_extract_docx",
    "_extract_pdf",
    "ask_human_for_resume",
    "ensure_resume",
    "extract_resume_text",
    "list_resume_files",
    "read_job_description",
]
