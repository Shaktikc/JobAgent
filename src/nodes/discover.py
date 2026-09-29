"""`discovery` — search LinkedIn, harvest job cards, filter, extract details.

Implemented in two parts:
- Task 5: read a single job URL and detect Easy Apply availability.
- Task 12: run the search from ``config/search.yaml``, apply filters, dedupe.

All network access goes through ``src/tools/linkedin.py`` and ``src/tools/guard.py``;
this node stays testable against saved HTML fixtures.
"""

from __future__ import annotations

# TODO(Task 5, Task 12)
