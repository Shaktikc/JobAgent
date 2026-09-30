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

The DOM-facing functions take a Playwright ``Page``; the decisions themselves
(classification, label lookup, screenshot naming) are pure and unit-testable
without a browser (SPEC.md §6).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Any

from playwright.sync_api import ElementHandle, Page

from src.tools.guard import Guard
from src.tools.store import Answer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Selectors — the single source of truth. Flat (no combinators); the live code
# scopes them under the modal element so a page-wide match cannot leak in.
# ---------------------------------------------------------------------------

EASY_APPLY_BUTTON_SELECTOR = (
    'button[data-view-name="job-apply-button"], '
    'button[data-testid="easy-apply-button"], '
    "button.jobs-apply-button"
)
# The live 2026 "Aero" Easy Apply modal is a native <dialog data-testid="dialog">
# (aria-labelledby="dialog-header"), not a div[role="dialog"]; keep both so the
# selector survives LinkedIn's UI generations.
MODAL_SELECTOR = (
    'dialog[data-testid="dialog"], '
    'dialog[aria-labelledby="dialog-header"], '
    'div[role="dialog"], '
    'div[data-testid="jobs-easy-apply-modal"]'
)
STEP_CONTROL_SELECTOR = "input, textarea, select"
TEXT_INPUT_SELECTOR = (
    'input[type="text"], input[type="number"], input[type="email"], '
    'input[type="tel"], input[type="url"], textarea'
)
FILE_INPUT_SELECTOR = 'input[type="file"]'
SUBMIT_BUTTON_SELECTOR = (
    'button[data-testid="submit-application-button"], '
    'button[aria-label="Submit application"]'
)
CONFIRMATION_SELECTOR = (
    'div[data-testid="post-apply-modal"], .artdeco-modal--layer-confirmation'
)

ARTIFACT_SUFFIX = "png"

# Text-like input types LinkedIn uses for free-text questions.
_TEXT_INPUT_TYPES = frozenset({"text", "number", "email", "tel", "url", "search"})


class FillError(RuntimeError):
    """A hard failure while filling. The caller marks the job `failed`."""


class WidgetKind(StrEnum):
    """What a form control is. Task 14 extends the handled set."""

    TEXT = "text"
    FILE = "file"
    SELECT = "select"
    RADIO = "radio"
    CHECKBOX = "checkbox"
    UNKNOWN = "unknown"


class Disposition(StrEnum):
    """What the engine will do with a widget."""

    FILL = "fill"
    UPLOAD = "upload"
    FLAG = "flag"


@dataclass(frozen=True)
class Widget:
    """A form control as seen by the (pure) decision layer."""

    label: str
    kind: WidgetKind
    required: bool = False


@dataclass(frozen=True)
class Decision:
    """The action for one widget, plus the answer to use when filling."""

    disposition: Disposition
    answer: Answer | None = None


@dataclass(frozen=True)
class FillReport:
    """The outcome of filling one modal step for one application."""

    job_id: str
    filled: tuple[Answer, ...]
    flagged: tuple[Widget, ...]
    resume_uploaded: bool
    screenshot: Path


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------


def widget_kind(tag: str, input_type: str | None) -> WidgetKind:
    """Classify a control by tag and input type. An input with no type is text."""
    tag = tag.lower()
    if tag == "textarea":
        return WidgetKind.TEXT
    if tag == "select":
        return WidgetKind.SELECT
    if tag == "input":
        resolved = (input_type or "text").lower()
        if resolved in _TEXT_INPUT_TYPES:
            return WidgetKind.TEXT
        if resolved == "file":
            return WidgetKind.FILE
        if resolved == "radio":
            return WidgetKind.RADIO
        if resolved == "checkbox":
            return WidgetKind.CHECKBOX
    return WidgetKind.UNKNOWN


def normalize_label(label: str) -> str:
    """Normalise a question label for matching (drop the required `*`, collapse space)."""
    return " ".join(label.replace("*", " ").split()).strip().lower()


def lookup_answer(answers: Mapping[str, Answer], label: str) -> Answer | None:
    """Find the answer for a question label, ignoring case and whitespace."""
    target = normalize_label(label)
    for key, answer in answers.items():
        if normalize_label(key) == target:
            return answer
    return None


def decide(widget: Widget, answers: Mapping[str, Answer]) -> Decision:
    """Decide what to do with one widget.

    Task 7 fills free-text fields and uploads the resume. Every other widget —
    including ones a later task will handle (select/radio/checkbox) — is left
    blank and flagged, never guessed.
    """
    if widget.kind is WidgetKind.TEXT:
        answer = lookup_answer(answers, widget.label)
        if answer is not None and answer.value:
            return Decision(Disposition.FILL, answer)
        return Decision(Disposition.FLAG)

    if widget.kind is WidgetKind.FILE:
        return Decision(Disposition.UPLOAD)

    return Decision(Disposition.FLAG)


def artifact_path(
    artifacts_dir: Path,
    job_id: str,
    *,
    timestamp: datetime | None = None,
    suffix: str = ARTIFACT_SUFFIX,
) -> Path:
    """Build a collision-resistant, filesystem-safe screenshot path."""
    moment = timestamp or datetime.now()
    stamp = moment.strftime("%Y%m%dT%H%M%S")
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", job_id).strip("._") or "job"
    return Path(artifacts_dir) / f"{safe_id}-{stamp}.{suffix}"


# ---------------------------------------------------------------------------
# Browser-facing logic (all actions pass through guard)
# ---------------------------------------------------------------------------

# Read the best available question label for a control, without inventing one.
_LABEL_JS = """
(el) => {
  const aria = el.getAttribute('aria-label');
  if (aria && aria.trim()) return aria.trim();
  if (el.labels && el.labels.length) {
    const text = Array.from(el.labels).map((l) => l.innerText).join(' ').trim();
    if (text) return text;
  }
  const wrapper = el.closest('label');
  if (wrapper && wrapper.innerText.trim()) return wrapper.innerText.trim();
  const placeholder = el.getAttribute('placeholder');
  if (placeholder && placeholder.trim()) return placeholder.trim();
  return el.getAttribute('name') || '';
}
"""

_REQUIRED_JS = "el => !!el.required || el.getAttribute('aria-required') === 'true'"
_TAG_JS = "el => el.tagName.toLowerCase()"


def _act(guard: Guard, action: Callable[[], Any], *, pace: bool = False) -> Any:
    """Run one browser action under guard: STOP is checked before every action.

    ``pace=True`` adds the randomized 20-90s delay for round-trip actions (opening
    the modal); per-field typing is local UI work and is not paced.
    """
    guard.check_stop()
    if pace:
        guard.pause_between_actions()
    return action()


def _element_widget(element: ElementHandle) -> Widget:
    tag = element.evaluate(_TAG_JS)
    return Widget(
        label=(element.evaluate(_LABEL_JS) or "").strip(),
        kind=widget_kind(tag or "", element.get_attribute("type")),
        required=bool(element.evaluate(_REQUIRED_JS)),
    )


def capture_screenshot(page: Page, artifacts_dir: Path, job_id: str) -> Path:
    """Save a PNG of the current form; taken for every application (criterion 12)."""
    path = artifact_path(artifacts_dir, job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path))
    return path


def list_step_widgets(page: Page) -> list[Widget]:
    """Read every control in the open modal, without changing anything.

    Used by orchestration to answer the real field labels before filling.
    """
    modal = page.query_selector(MODAL_SELECTOR)
    if modal is None:
        raise FillError("Easy Apply modal is not open.")
    return [_element_widget(element) for element in modal.query_selector_all(STEP_CONTROL_SELECTOR)]


def capture_confirmation(page: Page) -> str:
    """Read the post-submit confirmation, falling back to the resulting URL."""
    element = page.query_selector(CONFIRMATION_SELECTOR)
    if element is not None:
        text = (element.inner_text() or "").strip()
        if text:
            return text
    return page.url


def submit_application(page: Page, guard: Guard) -> str:
    """Click Submit — called only by the review gate after explicit approval.

    Returns the captured confirmation. Raises if the button is absent, so a job is
    never marked `applied` without an actual submission.
    """
    button = page.wait_for_selector(SUBMIT_BUTTON_SELECTOR, state="visible")
    if button is None:
        raise FillError("Submit button not found; application was not submitted.")
    _act(guard, button.click, pace=True)
    return capture_confirmation(page)


def open_application_form(page: Page, guard: Guard) -> ElementHandle:
    """Click Easy Apply and wait for the modal, guarded and paced."""
    button = page.wait_for_selector(EASY_APPLY_BUTTON_SELECTOR, state="visible")
    if button is None:
        raise FillError("Easy Apply button not found on this page.")
    _act(guard, button.click, pace=True)

    modal = page.wait_for_selector(MODAL_SELECTOR, state="visible")
    if modal is None:
        raise FillError("Easy Apply modal did not open after clicking Easy Apply.")
    return modal


def fill_current_step(
    page: Page,
    guard: Guard,
    job_id: str,
    answers: Mapping[str, Answer],
    *,
    resume_path: Path | None,
    artifacts_dir: Path,
) -> FillReport:
    """Fill the currently visible modal step, uploading the resume when provided.

    Always captures a screenshot, then returns the filled answers and the widgets
    left blank for review. Navigation to later steps is Task 13.
    """
    modal = page.wait_for_selector(MODAL_SELECTOR, state="visible")
    if modal is None:
        raise FillError("Easy Apply modal is not open.")

    filled: list[Answer] = []
    flagged: list[Widget] = []
    resume_uploaded = False

    for element in modal.query_selector_all(STEP_CONTROL_SELECTOR):
        widget = _element_widget(element)
        decision = decide(widget, answers)

        if decision.disposition is Disposition.FILL:
            assert decision.answer is not None  # FILL always carries an answer
            value = decision.answer.value
            _act(guard, partial(element.fill, value))
            filled.append(decision.answer)
        elif decision.disposition is Disposition.UPLOAD and resume_path is not None:
            _act(guard, partial(element.set_input_files, str(resume_path)))
            resume_uploaded = True
        else:
            # Unrecognized, unanswered, or a resume we were not given: leave blank.
            flagged.append(widget)

    screenshot = capture_screenshot(page, artifacts_dir, job_id)
    logger.info(
        "fill: step filled job_id=%s filled=%d flagged=%d resume_uploaded=%s",
        job_id,
        len(filled),
        len(flagged),
        resume_uploaded,
    )
    return FillReport(
        job_id=job_id,
        filled=tuple(filled),
        flagged=tuple(flagged),
        resume_uploaded=resume_uploaded,
        screenshot=screenshot,
    )


def _safe_screenshot(page: Page, artifacts_dir: Path, job_id: str) -> None:
    try:
        capture_screenshot(page, artifacts_dir, job_id)
    except Exception:  # best effort on an already-failing path
        logger.exception("fill: could not capture failure screenshot job_id=%s", job_id)


def fill_application(
    page: Page,
    guard: Guard,
    job_id: str,
    answers: Mapping[str, Answer],
    *,
    resume_path: Path | None,
    artifacts_dir: Path,
) -> FillReport:
    """Open the modal and fill one step; on a hard failure, screenshot then re-raise.

    Re-raising lets the caller (orchestration) mark the job `failed` rather than
    silently skipping it (SPEC.md §9).
    """
    guard.check_stop()
    try:
        open_application_form(page, guard)
        return fill_current_step(
            page,
            guard,
            job_id,
            answers,
            resume_path=resume_path,
            artifacts_dir=artifacts_dir,
        )
    except Exception:
        logger.exception("fill: application failed job_id=%s", job_id)
        _safe_screenshot(page, artifacts_dir, job_id)
        raise
