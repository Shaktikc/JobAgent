"""Classify Easy Apply failures and build a stable fingerprint for each one.

A fingerprint deliberately excludes the job title/company/URL: the same broken
step layout usually repeats across different jobs, and those occurrences should
update one bug entry instead of creating dozens of duplicates. The category, the
normalized error/notes, the step identity, and the field shape are enough to tell
two different dynamic-form failures apart.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

CATEGORY_LABELS = {
    "form_not_found": "Easy Apply form not found",
    "form_not_ready": "Easy Apply form did not finish rendering",
    "form_did_not_advance": "form did not advance to a new step",
    "navigation_missing": "navigation button disappeared",
    "navigation_disabled": "the only navigation button is disabled",
    "resume_control_missing": "no resume control on the form step",
    "resume_upload_failed": "resume upload failed",
    "required_question_unanswered": "required question was not answered",
    "required_field_not_filled": "required field was not filled",
    "submit_clicked": "Submit application was clicked",
    "browser_error": "browser/CDP error",
    # Task 3.2's LLM could not describe a resume or choose a match because the
    # provider/network failed. It is not a form-fill failure and the browser is
    # not the cause (BUG-080).
    "llm_call_failed": "the LLM call failed (network/provider)",
    "unknown_exception": "unexpected exception while filling the form",
    "unknown": "unclassified Easy Apply failure",
    # Task 1/2 (browse) hard stops. They are returned as outcomes rather than
    # raised, so a form-fill category is wrong for them (BUG-065).
    "login_not_completed": "the human did not log in",
    "search_no_results": "the job search returned no results",
    "search_filter_not_selected": "the Easy Apply filter was not selected",
    "easy_apply_job_missing": "no Easy Apply job could be opened",
    # Task 7/8: a returned results-pagination stop from the ``next_job`` node. Like
    # the browse stops, it is not a form-fill exception, so it must not be labelled
    # "unexpected exception while filling the form" (BUG-068).
    "pagination_failed": "the results pagination could not advance",
}

# Browse-stage (Tasks 1-2) hard stops, matched against the returned reason. These
# run before the fill markers so a search/login stop is never labelled "unexpected
# exception while filling the form" (BUG-065).
_BROWSE_MARKERS = (
    ("login not completed", "login_not_completed"),
    ("job search returned no results", "search_no_results"),
    ("easy apply filter not selected", "search_filter_not_selected"),
    ("no easy apply job", "easy_apply_job_missing"),
    ("no job easy apply button", "easy_apply_job_missing"),
    ("easy apply form did not open", "easy_apply_job_missing"),
)
_BROWSE_CATEGORIES = frozenset(category for _marker, category in _BROWSE_MARKERS)

# Categories whose symptom is already named by their label, so ``symptom_for``
# must not append the (redundant) raw reason after them.
_STANDALONE_SYMPTOM_CATEGORIES = _BROWSE_CATEGORIES | {
    "pagination_failed",
    "llm_call_failed",
}

# A stage's LLM failure (Task 3.2) is a provider/network stop. It must never fall
# through to the fill categories, where a previous job's Task 4 notes made it look
# like a broken form ("no resume control", BUG-080).
_LLM_ERROR_MARKERS = (
    "llm",
    "connection error",
    "openrouter",
    "could not describe the resume pool",
)

# Categories that are worth reopening the browser for. A required question that
# the agent genuinely cannot answer is left to Task 5 / the human; restarting the
# browser would just ask again. A required field whose control failed *is*
# recoverable: the DOM may have changed under a stale handle.
_RECOVERABLE = frozenset(
    {
        "form_not_found",
        "form_not_ready",
        "form_did_not_advance",
        "navigation_missing",
        "navigation_disabled",
        "resume_control_missing",
        "resume_upload_failed",
        "browser_error",
        "unknown_exception",
        "unknown",
        # A search/filter/job-selection stop can clear by re-running Task 1 in a
        # fresh browser; a missed login gate cannot (the human must do it).
        "search_no_results",
        "search_filter_not_selected",
        "easy_apply_job_missing",
        # A results-pagination click that did not move the list can clear by
        # reopening the results page and clicking the control again (BUG-068).
        "pagination_failed",
        # A transient provider/network failure can clear on a later attempt.
        "llm_call_failed",
    }
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _notes_of(task4: Any, notes: str) -> str:
    task_notes = getattr(task4, "notes", "") if task4 is not None else ""
    return _normalize(" ".join(part for part in (notes, task_notes) if part))


def _fields_of(task4: Any, fields: list[dict] | None = None) -> list[Any]:
    if fields is not None:
        return list(fields)
    if task4 is None:
        return []
    return list(getattr(task4, "fields", []) or [])


def _field_value(field: Any, key: str, default: Any = "") -> Any:
    if isinstance(field, dict):
        return field.get(key, default)
    return getattr(field, key, default)


def classify_failure(
    error: str = "",
    task4: Any = None,
    notes: str = "",
    *,
    stage: str = "fill",
) -> str:
    """Return the failure category for an exception and/or a Task 4 outcome.

    ``stage`` names the graph node the failure came from. A browse-stage
    (``browse``) stop is a returned search/login/job-selection outcome, so it is
    classified from those markers first and never falls through to the fill
    categories — where it used to become ``unknown_exception`` ("unexpected
    exception while filling the form") even though no form was involved (BUG-065).
    """
    text = _notes_of(task4, notes)
    combined = _normalize(f"{text} {error or ''}")

    if (stage or "fill").strip().lower() != "fill":
        for marker, category in _BROWSE_MARKERS:
            if marker in combined:
                return category
        # Task 7/8: a returned results-pagination stop is a ``next_job`` outcome,
        # not a form-fill exception (BUG-068).
        if "results pagination could not advance" in combined:
            return "pagination_failed"
        # Task 3.2's LLM/provider failure is not a form-fill exception either
        # (BUG-080). Only the match stage talks to the LLM in this guard.
        stage_name = (stage or "").strip().lower()
        if stage_name == "match" and any(
            marker in combined for marker in _LLM_ERROR_MARKERS
        ):
            return "llm_call_failed"
        # An unrecognised non-fill stop is still not a form-fill exception.
        return "unknown_exception" if error else "unknown"

    if bool(getattr(task4, "submitted", False)):
        return "submit_clicked"
    if task4 is not None and not bool(getattr(task4, "form_open", False)):
        return "form_not_found"

    # A required question the agent cannot answer is the actionable root cause and
    # is *not* browser-recoverable: a walk that stopped with "form did not advance"
    # because a required question was left unanswered would only stop again in a
    # fresh browser, so it is named before the soft navigation notes (BUG-052).
    fields = _fields_of(task4)
    if any(
        bool(_field_value(f, "required")) and not bool(_field_value(f, "known")) for f in fields
    ):
        return "required_question_unanswered"
    if any(
        bool(_field_value(f, "required"))
        and bool(_field_value(f, "known"))
        and not bool(_field_value(f, "filled"))
        for f in fields
    ):
        return "required_field_not_filled"

    # A stuck or disappearing navigation is the real, actionable stop; the
    # "no resume control" note is only a soft signal (the resume step often comes
    # later), so the advance failures are classified first (BUG-048).
    if "did not finish rendering" in combined:
        return "form_not_ready"
    if "form did not advance" in combined or "did not reach the final" in combined:
        return "form_did_not_advance"
    if "navigation button disappeared" in combined:
        return "navigation_missing"
    if "only navigation button is disabled" in combined:
        return "navigation_disabled"
    if "no resume control" in combined:
        return "resume_control_missing"
    if "resume upload failed" in combined:
        return "resume_upload_failed"

    if task4 is not None and not bool(getattr(task4, "resume_attached", False)):
        # The walk can finish a step without a resume control (it may appear on a
        # later step), but the overall fill is still incomplete.
        return "resume_control_missing"
    if any(
        token in combined
        for token in ("cdp", "websocket", "connection refused", "browser", "target closed")
    ):
        return "browser_error"
    if error or "fill raised" in text:
        return "unknown_exception"
    return "unknown"


def is_recoverable(category: str, task4: Any = None) -> bool:
    """True when reopening and re-filling could reasonably clear the failure."""
    if category == "required_field_not_filled":
        fields = _fields_of(task4)
        return any(
            bool(_field_value(f, "required"))
            and bool(_field_value(f, "known"))
            and not bool(_field_value(f, "filled"))
            and bool(_field_value(f, "error"))
            for f in fields
        )
    return category in _RECOVERABLE


def failure_fingerprint(
    category: str,
    *,
    error: str = "",
    task4: Any = None,
    step: str = "",
    fields: list[dict] | None = None,
) -> str:
    """Stable hash of a failure, independent of the job it happened on."""
    parts = [category, _normalize(error), _normalize(step)]
    for field in _fields_of(task4, fields):
        parts.append(
            "|".join(
                _normalize(str(_field_value(field, key)))
                for key in ("kind", "type", "question", "name", "option")
            )
        )
        parts.append("required" if _field_value(field, "required") else "optional")
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return digest[:20]


def category_label(category: str) -> str:
    """Human-readable label for a failure category."""
    return CATEGORY_LABELS.get(category, category.replace("_", " "))


def symptom_for(category: str, task4: Any = None, error: str = "") -> str:
    """A short, specific symptom for the bug log."""
    label = category_label(category)
    if category in _STANDALONE_SYMPTOM_CATEGORIES:
        # The label already names the stop; appending the reason would only
        # duplicate it ("the job search returned no results: browse: job search...").
        return label
    notes = _normalize(getattr(task4, "notes", "") if task4 is not None else "")
    if notes:
        return f"{label}: {notes[:240]}"
    if error:
        return f"{label}: {_normalize(error)[:200]}"
    return label


def fill_failure_reason(task4: Any) -> str:
    """Return why a Task 4 outcome is not a successful fill, or ``""``.

    This is the single source of truth for "did Task 4 finish?": the fill node, the
    self-healing loop, and ``verify`` must agree, or a crashed walk can look like a
    success and never trigger recovery (BUG-050). A fill succeeds only when the form
    opened, the resume was attached, every required known field was filled, and the
    walk reached the final review step (only **Submit application** left).
    """
    if task4 is None:
        return "fill: no Task 4 outcome"
    if bool(getattr(task4, "submitted", False)):
        return "fill: Submit was clicked (must never happen)"
    if not bool(getattr(task4, "form_open", False)):
        return "fill: Easy Apply form was not found"

    # Name a required question the agent could not answer before the generic walk
    # notes: it is the actionable reason the step did not advance, and it is not
    # recoverable by reopening the form (BUG-052).
    fields = _fields_of(task4)
    required_unknown = [
        f for f in fields if _field_value(f, "required") and not _field_value(f, "known")
    ]
    if required_unknown:
        return "fill: required questions are unanswered: " + "; ".join(
            str(_field_value(f, "question") or _field_value(f, "name")) for f in required_unknown
        )
    required_unfilled = [
        f
        for f in fields
        if _field_value(f, "required")
        and _field_value(f, "known")
        and not _field_value(f, "filled")
    ]
    if required_unfilled:
        return "fill: required fields were not filled: " + "; ".join(
            str(_field_value(f, "question") or _field_value(f, "name")) for f in required_unfilled
        )

    notes = _normalize(getattr(task4, "notes", ""))
    if "did not finish rendering" in notes:
        return (
            "fill: the Easy Apply form did not finish rendering its fields or "
            "navigation buttons"
        )
    if "form did not advance" in notes or "did not reach the final" in notes:
        return "fill: form did not advance to a new step"
    if "only navigation button is disabled" in notes:
        return "fill: the only navigation button is disabled"
    if "navigation button disappeared" in notes:
        return "fill: navigation button disappeared before it could be clicked"
    if "resume upload failed" in notes:
        return "fill: resume upload failed"
    if "fill raised" in notes:
        return f"fill: {getattr(task4, 'notes', '')}"

    if not bool(getattr(task4, "resume_attached", False)):
        # "no resume control" on an early step is expected (the control usually
        # appears later); the failure is that no step ever attached the resume.
        return "fill: resume was not attached"

    if not bool(getattr(task4, "reached_terminal_step", False)):
        return "fill: the form did not reach the final review step"
    return ""


def recovery_reason(category: str, task4: Any = None) -> str:
    """Why a category is (or is not) eligible for automatic recovery."""
    if is_recoverable(category, task4):
        return f"{category_label(category)} is recoverable by reopening the form"
    return f"{category_label(category)} needs a human answer or code change"


__all__ = [
    "CATEGORY_LABELS",
    "category_label",
    "classify_failure",
    "failure_fingerprint",
    "fill_failure_reason",
    "is_recoverable",
    "recovery_reason",
    "symptom_for",
]
