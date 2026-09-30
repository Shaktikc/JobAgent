"""`review-gate` — the human checkpoint and the sole authority to submit.

Implemented in Task 8. Displays the job, the resume used, and every field with its
answer and provenance, then accepts approve / reject / edit.

Invariants (SPEC.md §8):
- No code path may submit without explicit approval here.
- Reject performs no submission (``status=rejected``).
- Approve performs exactly one submission and captures the confirmation
  (``status=applied``).
- ``--dry-run`` never submits, regardless of approval.

The decision logic is pure; ``review_application`` takes its prompt, output sink
and submit handler as arguments so the whole gate is unit-testable without a
browser or a real submission.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from src.nodes.fill import normalize_label
from src.state import JobState
from src.tools.store import Answer, JobStatus


class ReviewAction(StrEnum):
    """The human's choice at the gate."""

    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"
    QUIT = "quit"


@dataclass(frozen=True)
class ReviewResult:
    """The outcome of one visit to the review gate."""

    action: ReviewAction
    answers: tuple[Answer, ...]
    submitted: bool
    status: JobStatus
    confirmation: str | None = None


_APPROVE_TOKENS = frozenset({"a", "approve", "y", "yes"})
_REJECT_TOKENS = frozenset({"r", "reject", "n", "no"})
_EDIT_TOKENS = frozenset({"e", "edit"})
_QUIT_TOKENS = frozenset({"q", "quit", "cancel"})


def parse_action(raw: str) -> ReviewAction | None:
    """Map a typed command to an action; ``None`` means re-prompt."""
    token = raw.strip().lower()
    if token in _APPROVE_TOKENS:
        return ReviewAction.APPROVE
    if token in _REJECT_TOKENS:
        return ReviewAction.REJECT
    if token in _EDIT_TOKENS:
        return ReviewAction.EDIT
    if token in _QUIT_TOKENS:
        return ReviewAction.QUIT
    return None


def render_review(
    job: JobState,
    answers: Sequence[Answer],
    *,
    resume_file: str | None = None,
) -> str:
    """Render the job, the resume used, and every field/answer/provenance."""
    lines = [
        "=== Review application ===",
        f"Job:    {job.get('title', '')} at {job.get('company', '')}",
        f"URL:    {job.get('url', '')}",
        f"Resume: {resume_file or '(none)'}",
        "",
        "Fields:",
    ]
    for answer in answers:
        shown = answer.value if answer.value else "(blank)"
        lines.append(f"  [{answer.provenance.value}] {answer.field} = {shown}")
    return "\n".join(lines)


def apply_edit(answers: Sequence[Answer], field: str, value: str) -> tuple[Answer, ...]:
    """Return a new answer list with one field's value replaced.

    Matches the field case- and whitespace-insensitively (like the fill layer).
    Raises ``KeyError`` when no field matches, so a typo never silently does nothing.
    """
    target = normalize_label(field)
    edited = list(answers)
    for index, answer in enumerate(edited):
        if normalize_label(answer.field) == target:
            edited[index] = replace(answer, value=value)
            return tuple(edited)
    raise KeyError(f"no such field: {field!r}")


def resolve_outcome(action: ReviewAction, *, dry_run: bool) -> tuple[bool, JobStatus]:
    """Map an action to (did_submit, resulting status).

    ``--dry-run`` short-circuits approval to no submission, leaving the job
    ``filled`` so it is re-offerable. Reject and quit never submit.
    """
    if action is ReviewAction.REJECT:
        return False, JobStatus.REJECTED
    if action is ReviewAction.QUIT:
        return False, JobStatus.FILLED
    if dry_run:
        return False, JobStatus.FILLED
    return True, JobStatus.APPLIED


def _prompt_or_quit(prompt: Callable[[str], str], message: str) -> str | None:
    """Prompt, treating Ctrl-C / end-of-input as "quit the gate"."""
    try:
        return prompt(message)
    except (EOFError, KeyboardInterrupt):
        return None


def review_application(
    job: JobState,
    answers: Sequence[Answer],
    *,
    dry_run: bool,
    resume_file: str | None = None,
    prompt: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
    submit: Callable[[], str] | None = None,
) -> ReviewResult:
    """Show the review and act on the human's decision.

    The only place in the codebase that may call ``submit`` — and only after an
    explicit approve outside dry-run. ``submit`` is called at most once.
    """
    current = tuple(answers)

    action: ReviewAction
    while True:
        out(render_review(job, current, resume_file=resume_file))

        raw = _prompt_or_quit(prompt, "Approve / reject / edit / quit [a/r/e/q]: ")
        if raw is None:
            action = ReviewAction.QUIT
            break

        parsed = parse_action(raw)
        if parsed is None:
            out(f"Unrecognized command: {raw!r}. Enter a, r, e or q.")
            continue

        if parsed is ReviewAction.EDIT:
            field = _prompt_or_quit(prompt, "Field to edit: ")
            value = _prompt_or_quit(prompt, "New value: ")
            if field is None or value is None:
                action = ReviewAction.QUIT
                break
            try:
                current = apply_edit(current, field, value)
            except KeyError:
                out(f"No field matching {field!r}.")
            continue

        action = parsed
        break

    submitted, status = resolve_outcome(action, dry_run=dry_run)
    confirmation: str | None = None
    if submitted:
        if submit is None:
            raise RuntimeError("approval requires a submit handler but none was provided")
        confirmation = submit()

    return ReviewResult(
        action=action,
        answers=current,
        submitted=submitted,
        status=status,
        confirmation=confirmation,
    )
