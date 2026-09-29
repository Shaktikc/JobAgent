"""`filling` — Playwright automation of the multi-step Easy Apply modal.

Implemented across Task 7 (single-step fields, resume upload, per-application
screenshots), Task 13 (multi-step navigation through Next/Review), and Task 14
(dropdowns, radios, checkboxes, and unknown-widget handling).

Rules:
- Selectors are module-level constants here, never inline in logic.
- Every browser action routes through ``src/tools/guard.py``.
- A screenshot of the filled form is saved to ``data/artifacts/`` for **every**
  application.
- An unrecognized required widget is left blank and surfaced as ``NEEDS_REVIEW``
  — never guessed, never a silent job skip.
"""

from __future__ import annotations

# TODO(Task 7, Task 13, Task 14)
