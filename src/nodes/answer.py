"""`answering` — map resume text and facts onto Easy Apply form questions.

Implemented in two parts:
- Task 6: deterministic facts rule engine and the ``Answer`` type carrying
  provenance and confidence (no LLM).
- Task 10: LLM integration behind the rules, with a confidence threshold that
  turns low-confidence answers into ``NEEDS_REVIEW`` rather than guesses.

Rules always take precedence over the LLM. Every field yields exactly one answer
with a ``Provenance`` value; nothing is ever left silently empty (SPEC.md §5, §7).
"""

from __future__ import annotations

# TODO(Task 6, Task 10)
