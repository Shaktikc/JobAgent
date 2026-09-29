"""`review-gate` — the human checkpoint and the sole authority to submit.

Implemented in Task 8. Displays the job, the resume used, and every field with its
answer and provenance, then accepts approve / reject / edit.

Invariants (SPEC.md §8):
- No code path may submit without explicit approval here.
- Reject performs no submission (``status=rejected``).
- Approve performs exactly one submission and captures the confirmation
  (``status=applied``).
- ``--dry-run`` never submits, regardless of approval.
"""

from __future__ import annotations

# TODO(Task 8)
