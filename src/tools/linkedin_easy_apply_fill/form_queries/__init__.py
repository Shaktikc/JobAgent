"""Task 4: DOM queries and readers for the open Easy Apply form.

This package holds the JavaScript the fill flow injects to inspect the open Easy
Apply form - its fields, its resume controls, and its buttons - and the async
readers that wrap those queries. The form is dynamic, so its steps, fields, and
resume control (a radio list, a ``<select>``, a file input, or an "Upload
resume" button that reveals one) are discovered at runtime rather than assumed.

The code is split by concern:

- :mod:`~src.tools.linkedin_easy_apply_fill.form_queries.scripts` - the injected
  query scripts and the ``findApplyRoot()`` injection helper.
- :mod:`~src.tools.linkedin_easy_apply_fill.form_queries.readers` - the async
  readers over those scripts.

Every name that used to live in the single ``form_queries`` module is re-exported
here, so existing imports keep working unchanged.
"""

from __future__ import annotations

from src.tools.linkedin_easy_apply_fill.form_queries.readers import (
    enumerate_form_fields,
    read_form,
    read_form_buttons,
    read_resume_info,
    read_resume_options,
)
from src.tools.linkedin_easy_apply_fill.form_queries.scripts import (
    _ENUMERATE_FORM_QUERY,
    _FORM_BUTTONS_QUERY,
    _RESUME_OPTIONS_QUERY,
    _with_apply_root,
)

__all__ = [
    "_ENUMERATE_FORM_QUERY",
    "_FORM_BUTTONS_QUERY",
    "_RESUME_OPTIONS_QUERY",
    "_with_apply_root",
    "enumerate_form_fields",
    "read_form",
    "read_form_buttons",
    "read_resume_info",
    "read_resume_options",
]
