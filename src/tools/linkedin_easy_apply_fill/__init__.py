"""Task 4: fill the open Easy Apply form and attach the resume (without submitting).

This package owns Task 4's interactive fill flow, split out of
:mod:`src.tools.browser`:

1. Enumerate the form's fields and controls (text inputs, selects, radio buttons,
   checkboxes, date pickers, and the resume upload control).
2. For each question, ask the LLM (Task 4.1/10) to classify it and answer it from
   the store — copying a stored answer or deriving one the stored entries entail,
   always citing the stored key(s) it used (see :mod:`src.tools.llm_answers` and
   :mod:`src.tools.llm_answer_reasoning`). Task 12 wraps that chooser with a
   job-context chooser for free-text questions about this job/employer/role, so
   those are answered (and evidence-grounded) from the current job description
   and selected resume. Questions neither source can ground are left for Task 5
   (or flagged). Attach the resume chosen by Task 3, preferring a resume
   already listed on the form over uploading a duplicate.
3. Advance through multi-step forms, stopping before **Submit application**.

The form is dynamic, so its steps, fields, and resume control (a radio list, a
``<select>``, a file input, or an "Upload resume" button that reveals one) are
discovered at runtime rather than assumed. Task 5's ask-the-human code lives in
:mod:`src.tools.linkedin_ask_human` and is called from here when the LLM cannot
answer a question.

The flow is split across six submodules by concern:

- :mod:`~src.tools.linkedin_easy_apply_fill.form_queries` — the injected DOM
  queries and the readers that wrap them.
- :mod:`~src.tools.linkedin_easy_apply_fill.required_only` — answer only the
  required (``*``) questions; optional ones are dropped untouched.
- :mod:`~src.tools.linkedin_easy_apply_fill.field_filling` — fill one step's
  known fields.
- :mod:`~src.tools.linkedin_easy_apply_fill.checkbox_groups` — answer a checkbox
  (multi-select) question as one group.
- :mod:`~src.tools.linkedin_easy_apply_fill.resume_attachment` — attach the
  Task 3 resume wherever the dynamic form exposes it.
- :mod:`~src.tools.linkedin_easy_apply_fill.form_walk` — walk the form step by
  step and stop before Submit.

Every name that used to live in the single ``linkedin_easy_apply_fill`` module is
re-exported here, so ``from src.tools.linkedin_easy_apply_fill import ...`` (and
:mod:`src.tools.browser`'s lazy re-exports) keep working unchanged.

The browser interaction uses browser-use's deterministic CDP actor API
(``Page`` / ``Element``); the LLM is used only to choose answers, never to drive
the browser.
"""

from __future__ import annotations

from src.tools.linkedin_easy_apply_fill.field_filling import (
    _FILL_INPUT_JS,
    _FILL_SELECT_JS,
    _SELECT_PLACEHOLDERS,
    _choice_hint,
    _control_already_answered,
    _decide,
    _fill_field,
    _fill_step,
    _select_value_for,
)
from src.tools.linkedin_easy_apply_fill.form_queries import (
    _ENUMERATE_FORM_QUERY,
    _FORM_BUTTONS_QUERY,
    _RESUME_OPTIONS_QUERY,
    _with_apply_root,
    enumerate_form_fields,
    read_form,
    read_form_buttons,
    read_resume_info,
    read_resume_options,
)
from src.tools.linkedin_easy_apply_fill.form_walk import (
    _MAX_FORM_STEPS,
    _blocked_note,
    _blocking_questions,
    _form_signature,
    _task4_ok,
    _task4_on_page,
)
from src.tools.linkedin_easy_apply_fill.required_only import (
    has_required_marker,
    is_required_field,
    only_required_fields,
)
from src.tools.linkedin_easy_apply_fill.resume_attachment import (
    _attach_resume,
    _resume_file_selector,
    _resume_listed_names,
    upload_file_via_cdp,
)

__all__ = [
    "_ENUMERATE_FORM_QUERY",
    "_FILL_INPUT_JS",
    "_FILL_SELECT_JS",
    "_FORM_BUTTONS_QUERY",
    "_MAX_FORM_STEPS",
    "_RESUME_OPTIONS_QUERY",
    "_SELECT_PLACEHOLDERS",
    "_attach_resume",
    "_blocked_note",
    "_blocking_questions",
    "_choice_hint",
    "_control_already_answered",
    "_decide",
    "_fill_field",
    "_fill_step",
    "_form_signature",
    "_resume_file_selector",
    "_resume_listed_names",
    "_select_value_for",
    "_task4_ok",
    "_task4_on_page",
    "_with_apply_root",
    "enumerate_form_fields",
    "has_required_marker",
    "is_required_field",
    "only_required_fields",
    "read_form",
    "read_form_buttons",
    "read_resume_info",
    "read_resume_options",
    "upload_file_via_cdp",
]
