"""Task 16: strict resume gate and safe closing of a skipped Easy Apply form.

Two responsibilities:

1. **The gate.** Strict resume matching (``AUTOJOB_SESSION_REQUIRE_RESUME_MATCH``,
   on by default) applies to a job only when the Task 3.2 LLM chose an existing
   resume and rated it a **strong** fit. Anything else — **none**, ``partial``, a
   missing rating, an empty pool — is a clean skip, not an error, and never uses
   the Task 3.1 remembered-resume / human-upload fallbacks.
2. **Closing the skipped job's form.** Task 2 opens the Easy Apply form before
   Task 3 matches, so a skip must close that modal before the results list can be
   used again (:func:`close_easy_apply_form`). Only dismiss/close/discard controls
   inside the open form are clicked — never **Submit application**, **Next**, or
   **Update profile**.

The module contains no LLM or matching logic of its own; the match stays with
Task 3.2 (:mod:`src.tools.resume_descriptions`).
"""

from __future__ import annotations

import asyncio
import re

from src.configuration import Settings
from src.state import (
    JobDescription,
    SkippedJobRecord,
    Task2Outcome,
    Task3Outcome,
    Task16Outcome,
)
from src.tools.browser import _element_label, _query_elements, _safe

# Buttons inside the open Easy Apply surface. The label filter below is what makes
# the scan safe: the form's own Next/Review/Submit buttons never match.
_MODAL_BUTTON_SELECTORS = (
    "div.jobs-easy-apply-modal button",
    "div[role='dialog'] button",
    "dialog[open] button",
    ".artdeco-modal button",
    'button[aria-label="Dismiss" i]',
    'button[aria-label="Close" i]',
    "button.artdeco-modal__dismiss",
    "button[data-test-modal-close-btn]",
)

_CLOSE_LABELS = frozenset({"dismiss", "close", "x"})
_DISCARD_LABELS = frozenset({"discard", "discard application"})
_CANCEL_LABELS = frozenset({"cancel"})

# Bounded attempts: the X usually closes immediately; a "Discard application?"
# confirmation needs one more click. Never loop forever on a stuck modal.
_MAX_CLOSE_ATTEMPTS = 3
_CLOSE_POLL_SECONDS = 0.5


def is_strict_resume_match(settings: Settings) -> bool:
    """True when only a strong existing-resume match may be applied to."""
    return bool(settings.session.require_resume_match)


def should_skip_job(outcome: Task3Outcome | None, settings: Settings) -> bool:
    """True when ``outcome`` is a clean Task 16 skip (strict mode, no error).

    A Task 3.2 error (unconfigured LLM, unusable reply, undescribable resume) is a
    hard failure and must keep failing the run, so it is never turned into a skip.
    """
    if outcome is None or not is_strict_resume_match(settings):
        return False
    if outcome.error:
        return False
    return not (outcome.selected_path and outcome.fit == "strong")


def skip_record(
    outcome: Task3Outcome | None, task2: Task2Outcome | None = None
) -> SkippedJobRecord:
    """Build the audit record for a skipped job."""
    description = (outcome.job_description if outcome else None) or JobDescription()
    title = (description.title or (task2.job_title if task2 is not None else "") or "").strip()
    return SkippedJobRecord(
        index=task2.job_index if task2 is not None else None,
        title=title,
        company=(description.company or "").strip(),
        fit=((outcome.fit if outcome is not None else "") or "none").strip(),
        rationale=((outcome.rationale if outcome is not None else "") or "").strip(),
    )


def record_skip(
    task16: Task16Outcome | None,
    outcome: Task3Outcome | None,
    task2: Task2Outcome | None = None,
) -> Task16Outcome:
    """Append ``outcome`` to the run's Task 16 skip record and count it."""
    task16 = task16 or Task16Outcome(enabled=True)
    task16.enabled = True
    task16.jobs_skipped += 1
    task16.skipped.append(skip_record(outcome, task2))
    return task16


def normalize_title(title: str) -> str:
    """Normalize a job title for the append-only ``skipped_titles`` set."""
    return re.sub(r"\s+", " ", (title or "").strip().lower())


async def _modal_is_open(page) -> bool:
    """True while the Easy Apply form/modal is still showing."""
    from src.tools.linkedin_job_apply_button import read_apply_modal  # keep light

    opened, _text = await read_apply_modal(page)
    return opened


def _normalize_label(label: str) -> str:
    return re.sub(r"\s+", " ", (label or "").strip().lower()).rstrip(".")


async def _click_labelled_button(page, labels: frozenset[str]) -> bool:
    """Click the first button inside the open form whose label is allowed."""
    for selector in _MODAL_BUTTON_SELECTORS:
        for element in await _query_elements(page, selector):
            label = _normalize_label(await _element_label(element))
            if label in labels:
                await _safe(element.click())
                return True
    return False


async def close_easy_apply_form(
    page,
    settings: Settings | None = None,
    notify=None,
    *,
    attempts: int = _MAX_CLOSE_ATTEMPTS,
) -> bool:
    """Close an open Easy Apply form without submitting it (Task 16).

    Returns ``True`` when the form is gone (including when it was never open) and
    ``False`` when it could not be closed within the bounded attempts. Only
    dismiss/close controls are clicked first; if a "Discard application?"
    confirmation appears, its **Discard** button is used (the draft is being
    skipped anyway). **Submit application** is never clicked.
    """
    del settings  # kept for a uniform browser-helper signature
    if page is None:
        return True
    notify = notify or (lambda _message: None)
    for attempt in range(max(1, attempts)):
        if not await _modal_is_open(page):
            return True
        if attempt == 0:
            clicked = await _click_labelled_button(page, _CLOSE_LABELS)
        elif attempt == 1:
            clicked = await _click_labelled_button(page, _DISCARD_LABELS)
        else:
            clicked = await _click_labelled_button(
                page, _CLOSE_LABELS | _CANCEL_LABELS | _DISCARD_LABELS
            )
        if not clicked:
            # No close control on the first pass may mean the form is already a
            # "Discard application?" confirmation; try the discard control next.
            if attempt == 0:
                continue
            break
        await asyncio.sleep(_CLOSE_POLL_SECONDS)
    if await _modal_is_open(page):
        notify(
            "Task 16: the Easy Apply form did not close; stopping instead of "
            "clicking through it."
        )
        return False
    return True


__all__ = [
    "close_easy_apply_form",
    "is_strict_resume_match",
    "normalize_title",
    "record_skip",
    "should_skip_job",
    "skip_record",
]
