"""Unit tests for the browser-use task builders.

Pure only: no browser, no LLM, and no ``browser_use`` import — the live functions
import it lazily. These tests pin the two safety-critical properties we can prove
without a browser: answers are injected via substitution tokens, and the fill task
carries a hard no-submit instruction.
"""

from __future__ import annotations

from pathlib import Path

from src.tools.browser_agent import (
    NO_SUBMIT_EXTENSION,
    answers_to_field_instructions,
    build_fill_task,
    build_no_submit_system_message,
    build_submit_system_message,
    build_submit_task,
    sensitive_data_for,
)
from src.tools.store import Answer, Provenance

ANSWERS = (
    Answer("City", "Boston", Provenance.RESUME, 1.0),
    Answer("Do you require sponsorship?", "", Provenance.NEEDS_REVIEW, 0.0),
    Answer("Expected salary", "110000", Provenance.FACTS_RULE, 1.0),
)


def test_only_answered_fields_become_instructions() -> None:
    instructions = answers_to_field_instructions(ANSWERS)

    labels = [i.label for i in instructions]
    assert labels == ["City", "Expected salary"]  # NEEDS_REVIEW/empty skipped


def test_placeholders_are_stable_and_referenced_in_the_task() -> None:
    instructions = answers_to_field_instructions(ANSWERS)

    assert [i.placeholder for i in instructions] == ["ANSWER_1", "ANSWER_3"]
    assert instructions[0].token == "<ANSWER_1>"


def test_sensitive_data_maps_each_placeholder_to_its_value() -> None:
    instructions = answers_to_field_instructions(ANSWERS)

    data = sensitive_data_for(instructions)

    assert data == {"ANSWER_1": "Boston", "ANSWER_3": "110000"}


def test_fill_task_includes_job_answers_and_a_hard_no_submit_rule() -> None:
    instructions = answers_to_field_instructions(ANSWERS)

    task = build_fill_task(
        title="Senior Data Analyst",
        company="Acme Analytics",
        url="https://www.linkedin.com/jobs/view/4012345678/",
        instructions=instructions,
        resume_path=Path("resumes/data-analyst.pdf"),
    )

    assert "Senior Data Analyst" in task
    assert "Acme Analytics" in task
    assert "https://www.linkedin.com/jobs/view/4012345678/" in task
    assert '<ANSWER_1>' in task  # values are referenced by token, not pasted
    assert "Boston" not in task
    assert "data-analyst.pdf" in task  # resume upload instruction
    assert NO_SUBMIT_EXTENSION in task
    assert "Leave any field that is not listed above blank" in task


def test_fill_task_without_answers_still_forbids_submitting() -> None:
    task = build_fill_task(
        title="Role",
        company="Co",
        url="https://x/",
        instructions=(),
        resume_path=None,
    )

    assert "no fields were answerable" in task
    assert NO_SUBMIT_EXTENSION in task


def test_submit_task_is_explicit_but_bounded_to_one() -> None:
    task = build_submit_task(
        title="Senior Data Analyst",
        company="Acme Analytics",
        url="https://www.linkedin.com/jobs/view/4012345678/",
    )

    assert "Submit this LinkedIn Easy Apply application" in task
    assert "Senior Data Analyst" in task
    assert "exactly once" in task


def test_system_messages_gate_submission() -> None:
    gate = build_no_submit_system_message()
    assert "NEVER click Submit" in gate

    extended = build_no_submit_system_message("Extra: stay on this page.")
    assert gate in extended and "Extra" in extended

    submit = build_submit_system_message()
    assert "explicit human approval" in submit


# --- multi-step modals (the 2026-09-30 real dry-run showed "1/4 pages") ------


def test_fill_task_walks_every_step_but_still_never_submits() -> None:
    """The Easy Apply modal is multi-step; the fill must advance with Next, not stop.

    The real Talent Forge form was "1/4 pages". A single-step fill leaves steps 2-4
    untouched and the answers lost. The task must tell the agent to click Next to
    continue filling, stop at the final review, and never click Submit.
    """
    task = build_fill_task(
        title="Full Stack Engineer",
        company="Talent Forge Group",
        url="https://www.linkedin.com/jobs/view/4468706364/",
        instructions=(),
        resume_path=None,
    )

    assert "Next" in task  # advance through the modal's steps
    assert "Submit" in task  # the forbidden control is named
    assert NO_SUBMIT_EXTENSION in task  # ...and still forbidden


def test_read_form_task_collects_labels_across_all_steps() -> None:
    """Reading only "the form it currently shows" misses later steps' fields.

    The label read must walk the modal with Next to expose every question, without
    submitting, so the rules can answer all of them.
    """
    from src.nodes.fill import READ_FORM_TASK

    assert "Next" in READ_FORM_TASK or "Continue" in READ_FORM_TASK
    assert "every" in READ_FORM_TASK  # all steps, not just the first
    assert "Submit" in READ_FORM_TASK  # named as forbidden
