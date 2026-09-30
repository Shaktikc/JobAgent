"""`filling` — browser-use agent fill, plus the gate-only submit (Task 17).

Rewritten in ADR 0001. The hand-written selector/fill code is gone; the
agent fills the form from a task built by :mod:`src.tools.browser_agent`. Rules:

- **The agent never submits.** :func:`fill_application` uses the no-submit system
  message; submission is :func:`submit_application`, called only by the review gate.
- Answers are injected via ``sensitive_data`` placeholders, not pasted into prompts.
- A screenshot of the filled form is saved to ``data/artifacts/`` for **every**
  application (criterion 12).
- Fields the agent could not fill are surfaced for review, never guessed.

The marshalling/decision helpers are pure and unit-testable without a browser or an
LLM: ``normalize_label``, ``artifact_path``, ``reconcile_outcome``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.tools import browser_agent
from src.tools.browser_agent import FieldInstruction
from src.tools.store import Answer

logger = logging.getLogger(__name__)

ARTIFACT_SUFFIX = "png"


class FillError(RuntimeError):
    """A hard failure while filling. The caller marks the job `failed`."""


@dataclass(frozen=True)
class FillReport:
    """The outcome of filling one application."""

    job_id: str
    filled: tuple[Answer, ...]
    flagged: tuple[str, ...]
    resume_uploaded: bool
    screenshot: Path


class FormFields(BaseModel):
    """The labels the agent found on the open Easy Apply form."""

    fields: list[str] = []


class FillOutcome(BaseModel):
    """The agent's self-report of what it filled."""

    filled_fields: list[str] = []
    unfilled_fields: list[str] = []
    resume_uploaded: bool = False


READ_FORM_TASK = (
    "LinkedIn is showing a job page. If the LinkedIn Easy Apply form is not already "
    'open, click the "Easy Apply" button to open it, then list the label of every '
    "question and field the form currently shows, in order.\n\n"
    "Read only: do NOT type into any field, do NOT upload anything, and do NOT click "
    "Submit. Return the field labels as structured output."
)

_WRITE_EXTRA = (
    "Any field the form shows that is not listed above must be left blank and "
    "reported in `unfilled_fields`."
)

# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------


def normalize_label(label: str) -> str:
    """Normalise a question label for matching (drop the required `*`, collapse space)."""
    return " ".join(label.replace("*", " ").split()).strip().lower()


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


def reconcile_outcome(
    outcome: FillOutcome,
    answers: Iterable[Answer],
) -> tuple[tuple[Answer, ...], tuple[str, ...]]:
    """Map the agent's self-report back onto the answers we gave it.

    An answer with no value is always flagged (``NEEDS_REVIEW``), never treated as
    filled. An answer the agent explicitly reported unfilled is flagged too. Anything
    else is assumed filled — the agent starts from the instruction list, so silence
    means success, and the human still sees every value at the gate.
    """
    unfilled = {normalize_label(label) for label in outcome.unfilled_fields}
    filled: list[Answer] = []
    flagged: list[str] = []
    for answer in answers:
        if not answer.value or normalize_label(answer.field) in unfilled:
            flagged.append(answer.field)
        else:
            filled.append(answer)
    return tuple(filled), tuple(flagged)


# ---------------------------------------------------------------------------
# Live layer
# ---------------------------------------------------------------------------


async def capture_screenshot(browser: Any, artifacts_dir: Path, job_id: str) -> Path:
    """Save a PNG of the current form; taken for every application (criterion 12)."""
    path = artifact_path(artifacts_dir, job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    await browser.take_screenshot(path=str(path))
    return path


async def open_and_read_fields(browser: Any, llm: Any, guard: Any) -> tuple[str, ...]:
    """Open the Easy Apply form and return the field labels the agent found."""
    result = await browser_agent.run_task(
        READ_FORM_TASK,
        llm=llm,
        browser=browser,
        system_message=browser_agent.build_no_submit_system_message(),
        output_model_schema=FormFields,
        guard=guard,
    )
    found = result.structured_output
    if isinstance(found, FormFields):
        return tuple(label for label in found.fields if label.strip())
    return ()


def _fill_instructions(answers: Iterable[Answer]) -> tuple[FieldInstruction, ...]:
    return browser_agent.answers_to_field_instructions(answers)


async def fill_application(
    browser: Any,
    llm: Any,
    guard: Any,
    job: Mapping[str, Any],
    answers: Iterable[Answer],
    *,
    resume_path: Path | None,
    artifacts_dir: Path,
) -> FillReport:
    """Fill the open Easy Apply form with the agent, then screenshot it.

    On a hard failure the caller (orchestration) marks the job `failed` (SPEC.md §9).
    """
    job_id = str(job.get("job_id", ""))
    instructions = _fill_instructions(answers)
    task = browser_agent.build_fill_task(
        title=str(job.get("title", "")),
        company=str(job.get("company", "")),
        url=str(job.get("url", "")),
        instructions=instructions,
        resume_path=resume_path,
    )
    result = await browser_agent.run_task(
        task,
        llm=llm,
        browser=browser,
        system_message=browser_agent.build_no_submit_system_message(_WRITE_EXTRA),
        sensitive_data=browser_agent.sensitive_data_for(instructions),
        available_file_paths=[resume_path] if resume_path is not None else None,
        output_model_schema=FillOutcome,
        guard=guard,
    )
    raw = result.structured_output
    outcome = raw if isinstance(raw, FillOutcome) else FillOutcome()
    filled, flagged = reconcile_outcome(outcome, answers)

    screenshot = await capture_screenshot(browser, artifacts_dir, job_id)
    logger.info(
        "fill: application filled job_id=%s filled=%d flagged=%d resume_uploaded=%s",
        job_id,
        len(filled),
        len(flagged),
        outcome.resume_uploaded,
    )
    return FillReport(
        job_id=job_id,
        filled=filled,
        flagged=flagged,
        resume_uploaded=outcome.resume_uploaded,
        screenshot=screenshot,
    )


async def submit_application(
    browser: Any,
    llm: Any,
    guard: Any,
    job: Mapping[str, Any],
) -> str:
    """Submit exactly one application — called only by the review gate.

    Returns the confirmation text the agent reported. The gate is the sole caller
    (SPEC.md §8); this function is never reachable from ``--dry-run``.
    """
    task = browser_agent.build_submit_task(
        title=str(job.get("title", "")),
        company=str(job.get("company", "")),
        url=str(job.get("url", "")),
    )
    result = await browser_agent.run_task(
        task,
        llm=llm,
        browser=browser,
        system_message=browser_agent.build_submit_system_message(),
        guard=guard,
    )
    return result.final_result or ""
