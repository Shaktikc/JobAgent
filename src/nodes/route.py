"""`routing` — auto-index every resume in ``resumes/`` and pick the best per job.

Implemented in Task 11. There is no fixed taxonomy and no naming convention: each
PDF is parsed, its target role keywords are LLM-extracted once per file hash and
cached in SQLite, and jobs are matched against that index. ``config/resumes.yaml``
holds optional overrides only, and a low-confidence match falls back to
``default_variant`` and is flagged at review (SPEC.md §7).
"""

from __future__ import annotations

# TODO(Task 11)
