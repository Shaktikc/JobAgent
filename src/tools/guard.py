"""`guard` — pacing, daily cap, business hours, and the STOP sentinel.

Implemented in Task 4. Every network or browser action must pass through here
(SPEC.md §8). Values come from ``configuration.GuardSettings``; changing them is an
"ask first" action. Clock and sleep are injectable so tests are instant.

Also halts immediately on a LinkedIn rate-limit or checkpoint signal.
"""

from __future__ import annotations

# TODO(Task 4)
