"""`browser-use` agent integration — the AI-driven browser layer.

See ``docs/decisions/0001-browser-use-migration.md`` (ADR 0001). This module owns
everything that turns our data into a browser-use task and everything that runs the
agent, while preserving the project's hard safety invariants (``SPEC.md`` §8):

- **The agent never submits on its own.** :func:`build_fill_task` ends with a hard
  no-submit instruction; submission is a separate task (:func:`build_submit_task`)
  introduced only by the review gate after explicit approval.
- **Every run is guarded.** :func:`run_task` brackets the agent with
  ``guard.check_stop()`` and paces it with ``guard.pause_between_actions()``.
- **Answers are injected, not pasted.** :func:`sensitive_data_for` maps each answer
  to a browser-use ``sensitive_data`` placeholder so values are substituted by the
  framework rather than embedded in the prompt text.

The task builders and data marshalling are pure: no browser, no LLM, no
``browser_use`` import at module load. That keeps this module unit-testable and
importable even when the dependency is absent. ``browser_use`` is imported lazily
inside the live functions.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.tools.store import Answer

# Browser-use substitutes values into the task from ``sensitive_data``. A token is
# referenced as ``<KEY>`` in the task text and looked up by ``KEY`` in the mapping.
PLACEHOLDER_TEMPLATE = "ANSWER_{index}"

NO_SUBMIT_EXTENSION = (
    "You may ONLY read and fill this form. You must NEVER click Submit, "
    '"Submit application", "Apply", or any control that finalizes, sends, or '
    "submits the application. Submission is handled elsewhere and requires human "
    "approval. When the form is as complete as these instructions allow, stop and "
    "report what you filled and anything you could not answer. Never invent an "
    "answer for a field you were not given."
)

_SUBMIT_ONCE_EXTENSION = (
    "You have explicit human approval to submit this one application. Click the "
    "Submit control exactly once. Do not submit a second time, do not apply to any "
    "other job, and do not navigate away afterwards. Report the confirmation text "
    "shown by the page."
)

_ANSWER_INSTRUCTIONS_HEADER = (
    "Fill the LinkedIn Easy Apply form currently open for the job below. Work only "
    "on this application; do not search for other jobs.\n\n"
    "Use exactly these answers. The <TOKEN> placeholders are substituted for the "
    "real values automatically — reference the token exactly as shown:\n"
)

_LEAVE_BLANK = (
    "Leave any field that is not listed above blank. Never guess or invent a value."
)


class BrowserUseNotInstalledError(RuntimeError):
    """Raised when the live path is used but ``browser-use`` is not installed."""

    def __init__(self) -> None:
        super().__init__(
            "browser-use is not installed. Run `poetry add browser-use` and "
            "`poetry run browser-use install` (see "
            "docs/decisions/0001-browser-use-migration.md)."
        )


@dataclass(frozen=True)
class FieldInstruction:
    """One answer turned into a task instruction + a substitution placeholder."""

    label: str
    placeholder: str
    value: str

    @property
    def token(self) -> str:
        """The ``<TOKEN>`` form the agent sees in the task text."""
        return f"<{self.placeholder}>"


@dataclass(frozen=True)
class AgentRunResult:
    """A trimmed view of a browser-use ``Agent.run()`` result."""

    done: bool
    successful: bool | None
    final_result: str | None = None
    structured_output: Any = None
    output: Any = None


# ---------------------------------------------------------------------------
# Pure task building (unit-testable without a browser or an LLM)
# ---------------------------------------------------------------------------


def build_no_submit_system_message(extra: str | None = None) -> str:
    """System-prompt extension forbidding submission (the default gate message)."""
    return NO_SUBMIT_EXTENSION if not extra else f"{NO_SUBMIT_EXTENSION}\n\n{extra}"


def build_submit_system_message() -> str:
    """System-prompt extension for the one explicitly-approved submission."""
    return _SUBMIT_ONCE_EXTENSION


def answers_to_field_instructions(
    answers: Iterable[Answer],
) -> tuple[FieldInstruction, ...]:
    """Turn answers into ordered task instructions.

    Only answers with a non-empty value are included: blank or ``NEEDS_REVIEW``
    fields are deliberately omitted so the agent leaves them blank (SPEC.md §9),
    never guessing.
    """
    instructions: list[FieldInstruction] = []
    for index, answer in enumerate(answers, start=1):
        if not answer.value:
            continue
        instructions.append(
            FieldInstruction(
                label=answer.field,
                placeholder=PLACEHOLDER_TEMPLATE.format(index=index),
                value=answer.value,
            )
        )
    return tuple(instructions)


def sensitive_data_for(instructions: Sequence[FieldInstruction]) -> dict[str, str]:
    """Build browser-use ``sensitive_data`` from the field instructions."""
    return {instruction.placeholder: instruction.value for instruction in instructions}


def build_fill_task(
    *,
    title: str,
    company: str,
    url: str,
    instructions: Sequence[FieldInstruction],
    resume_path: Path | None = None,
) -> str:
    """Compose the fill task: job identity, answers, optional upload, no-submit rule."""
    lines = [
        _ANSWER_INSTRUCTIONS_HEADER.rstrip(),
        f'Job: "{title}" at {company}',
        f"URL: {url}",
        "",
    ]
    for instruction in instructions:
        lines.append(f'- Field "{instruction.label}" → type {instruction.token}')
    if not instructions:
        lines.append("- (no fields were answerable; leave the form blank)")

    if resume_path is not None:
        lines += [
            "",
            "If the form shows a resume/CV file upload control, upload this file:",
            f"  file: {resume_path.name}",
            f"  path: {resume_path}",
        ]

    lines += ["", _LEAVE_BLANK, "", NO_SUBMIT_EXTENSION]
    return "\n".join(lines)


def build_submit_task(*, title: str, company: str, url: str) -> str:
    """Compose the one-time submit task (only ever run after approval)."""
    return "\n".join(
        [
            "Submit this LinkedIn Easy Apply application. This is authorised.",
            f'Job: "{title}" at {company}',
            f"URL: {url}",
            "",
            _SUBMIT_ONCE_EXTENSION,
        ]
    )


# ---------------------------------------------------------------------------
# Live layer — imports browser_use lazily so the module stays importable and its
# pure tests run without the heavy dependency installed.
# ---------------------------------------------------------------------------


def build_openrouter_llm(model: str) -> Any:
    """Build the browser-use LLM client (OpenRouter, matching the T9/T10 plan)."""
    try:
        from browser_use import ChatOpenRouter
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        raise BrowserUseNotInstalledError() from exc

    return ChatOpenRouter(model=model)


async def run_task(
    task: str,
    *,
    llm: Any,
    browser: Any,
    system_message: str,
    sensitive_data: Mapping[str, str] | None = None,
    available_file_paths: Sequence[Path] | None = None,
    output_model_schema: type[Any] | None = None,
    guard: Any = None,
    max_actions_per_step: int = 5,
) -> AgentRunResult:
    """Run one browser-use task, bracketed by ``guard``.

    The whole run is treated as a single round-trip action: STOP is checked before
    and after, and the randomised pause is applied once before the run (not per
    internal LLM step, which the guard cannot see).
    """
    try:
        from browser_use import Agent
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        raise BrowserUseNotInstalledError() from exc

    if guard is not None:
        guard.check_stop()
        guard.pause_between_actions()

    agent: Any = Agent(
        task=task,
        llm=llm,
        browser=browser,
        extend_system_message=system_message,
        sensitive_data=dict(sensitive_data) if sensitive_data else None,
        available_file_paths=[str(p) for p in (available_file_paths or [])],
        output_model_schema=output_model_schema,
        max_actions_per_step=max_actions_per_step,
    )
    result = await agent.run()

    if guard is not None:
        guard.check_stop()

    return AgentRunResult(
        done=bool(getattr(result, "is_done", False)),
        successful=getattr(result, "is_successful", None),
        final_result=getattr(result, "final_result", None),
        structured_output=getattr(result, "structured_output", None),
        output=result,
    )
