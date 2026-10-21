"""Task 4: async readers over the Easy Apply form's DOM query scripts.

These wrap the injected scripts in
:mod:`~src.tools.linkedin_easy_apply_fill.form_queries.scripts` and parse their
JSON payloads. The browser interaction uses browser-use's deterministic CDP actor
API (``Page`` / ``Element``); the LLM is used only to choose answers, never to
drive the browser.
"""

from __future__ import annotations

from src.tools.browser import _loads, _safe
from src.tools.linkedin_easy_apply_fill.form_queries.scripts import (
    _ENUMERATE_FORM_QUERY,
    _FORM_BUTTONS_QUERY,
    _RESUME_OPTIONS_QUERY,
)


async def read_form(page) -> tuple[bool, str, list[dict], str]:
    """Return ``(form_open, step_title, fields, step)`` for the open form (Task 4).

    ``step`` is a stable identity for the current step (the modal's progress
    indicator plus its headings), so the walk can tell steps apart even when they
    hold no fillable controls (LinkedIn's review/edit steps).
    """
    payload = _loads(await _safe(page.evaluate(_ENUMERATE_FORM_QUERY), ""))
    return (
        bool(payload.get("open")),
        str(payload.get("title") or ""),
        list(payload.get("fields") or []),
        str(payload.get("step") or ""),
    )


async def enumerate_form_fields(page) -> tuple[bool, list[dict]]:
    """Return ``(form_open, fields)`` for the open Easy Apply form (Task 4)."""
    opened, _title, fields, _step = await read_form(page)
    return opened, fields


async def read_resume_info(page) -> dict:
    """Return the resume controls: ``options``, ``fileInput``, ``select``, ``uploadButton``.

    The form is dynamic, so the resume control may be a radio list, a
    ``<select>``, a file input, or an upload button that reveals the file input.
    """
    payload = _loads(await _safe(page.evaluate(_RESUME_OPTIONS_QUERY), ""))
    return {
        "options": list(payload.get("options") or []),
        "fileInput": bool(payload.get("fileInput")),
        "select": payload.get("select") or None,
        "uploadButton": payload.get("uploadButton") or None,
    }


async def read_resume_options(page) -> tuple[list[dict], bool]:
    """Return ``(listed_resume_options, file_input_present)`` for the form (Task 4)."""
    info = await read_resume_info(page)
    return info["options"], info["fileInput"]


async def read_form_buttons(page) -> list[dict]:
    """Return the Easy Apply modal's buttons (Task 4)."""
    payload = _loads(await _safe(page.evaluate(_FORM_BUTTONS_QUERY), ""))
    return list(payload.get("buttons") or [])
