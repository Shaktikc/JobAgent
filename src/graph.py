"""The StateGraph builder and compiler.

``langgraph.json`` points at ``build_graph`` in this module. The assembly is
implemented in Task 8 (minimal: single URL -> read -> answer -> fill -> review)
and completed in Task 15 (full loop with checkpointing and crash resume).

Browser, database and settings dependencies are injected through :class:`Runtime`
so the graph is a plain, testable pipeline; the no-argument studio entry point is
completed in Task 15.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from playwright.sync_api import Page

from src.configuration import AppSettings, FactsConfig, ResumeRoutingConfig
from src.nodes import answer as answering
from src.nodes import discover, fill, review
from src.state import JobState, RunState
from src.tools import store
from src.tools.guard import Guard

DRY_RUN_NOTICE = "Dry run: approval will fill and review but NEVER submit."
LIVE_RUN_NOTICE = "Live submit enabled (no --dry-run): approval at the gate will submit."


@dataclass
class Runtime:
    """Everything the minimal graph needs, injected once per run."""

    settings: AppSettings
    conn: sqlite3.Connection
    page: Page
    guard: Guard
    facts: FactsConfig
    resume_path: Path | None
    dry_run: bool
    job_url: str = ""
    prompt: Callable[[str], str] = input
    out: Callable[[str], None] = print


def resolve_default_resume(settings: AppSettings) -> Path | None:
    """Minimal resume choice until Task 11's auto-indexed routing lands.

    Uses ``resumes.yaml``'s ``default_variant`` when set, else the first PDF in
    ``resumes/``. Returns ``None`` when there is no resume to upload.
    """
    config = ResumeRoutingConfig.from_yaml(settings.paths.config / "resumes.yaml")
    if config.default_variant:
        return Path(config.default_variant)
    pdfs = sorted(settings.paths.resumes.glob("*.pdf"))
    return pdfs[0] if pdfs else None


# ---------------------------------------------------------------------------
# Nodes — thin functions over RunState; all I/O lives in src/tools and src/nodes
# ---------------------------------------------------------------------------


def _node_discover(runtime: Runtime, state: RunState) -> RunState:
    job = discover.read_job(runtime.page, state["job_url"], guard=runtime.guard)
    runtime.out(f"Read job: {job.get('title', '')} at {job.get('company', '')}")
    store.upsert_job(
        runtime.conn,
        store.Job(
            job_id=job["job_id"],
            title=job.get("title", ""),
            company=job.get("company", ""),
            url=job.get("url", ""),
            description=job.get("description", ""),
            status=store.JobStatus.SEEN,
        ),
    )
    return {"job": job}


def _node_answer(runtime: Runtime, state: RunState) -> RunState:
    """Open the modal and answer each real field label with the Task 6 rules."""
    fill.open_application_form(runtime.page, runtime.guard)
    labels = [widget.label for widget in fill.list_step_widgets(runtime.page) if widget.label]
    answers = answering.answer_fields(labels, runtime.facts)
    return {"answer_map": {answer.field: answer for answer in answers}}


def _node_fill(runtime: Runtime, state: RunState) -> RunState:
    job = state["job"]
    job_id = job["job_id"]
    try:
        report = fill.fill_current_step(
            runtime.page,
            runtime.guard,
            job_id,
            state.get("answer_map", {}),
            resume_path=runtime.resume_path,
            artifacts_dir=runtime.settings.paths.artifacts,
        )
    except Exception:
        store.set_job_status(runtime.conn, job_id, store.JobStatus.FAILED)
        raise

    # Review must show every field: the answers actually filled, plus a
    # NEEDS_REVIEW entry for each control left blank (never guessed).
    review_answers: list[store.Answer] = list(report.filled)
    for widget in report.flagged:
        review_answers.append(
            store.Answer(
                field=widget.label.strip() or "(unnamed field)",
                value="",
                provenance=store.Provenance.NEEDS_REVIEW,
                confidence=0.0,
            )
        )
    for answer in review_answers:
        store.record_answer(runtime.conn, job_id, answer)

    resume_file = (
        str(runtime.resume_path)
        if report.resume_uploaded and runtime.resume_path is not None
        else None
    )
    store.set_job_status(
        runtime.conn, job_id, store.JobStatus.FILLED, resume_file=resume_file
    )

    filled_job: JobState = {
        **job,
        "answers": review_answers,
        "resume_file": resume_file,
        "status": store.JobStatus.FILLED,
    }
    return {"job": filled_job, "status": store.JobStatus.FILLED.value}


def _node_review(runtime: Runtime, state: RunState) -> RunState:
    job = state["job"]
    submit = (
        None
        if runtime.dry_run
        else partial(fill.submit_application, runtime.page, runtime.guard)
    )
    result = review.review_application(
        job,
        job.get("answers", []),
        dry_run=runtime.dry_run,
        resume_file=job.get("resume_file"),
        prompt=runtime.prompt,
        out=runtime.out,
        submit=submit,
    )
    store.set_job_status(runtime.conn, job["job_id"], result.status)
    return {
        "review_action": result.action.value,
        "submitted": result.submitted,
        "confirmation": result.confirmation,
        "status": result.status.value,
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_graph(runtime: Runtime | None = None) -> Any:
    """Build and compile the minimal AutoJobApply graph.

    A :class:`Runtime` must be supplied; the no-argument studio entry point
    (``langgraph.json``) is completed in Task 15 when settings are loaded from the
    environment inside the nodes.
    """
    if runtime is None:
        raise RuntimeError(
            "build_graph needs a Runtime in Task 8; the studio entry point is "
            "completed in Task 15."
        )

    builder = StateGraph(RunState)
    builder.add_node("discover", partial(_node_discover, runtime))
    builder.add_node("answer", partial(_node_answer, runtime))
    builder.add_node("fill", partial(_node_fill, runtime))
    builder.add_node("review", partial(_node_review, runtime))
    builder.add_edge(START, "discover")
    builder.add_edge("discover", "answer")
    builder.add_edge("answer", "fill")
    builder.add_edge("fill", "review")
    builder.add_edge("review", END)
    return builder.compile()


def run_single_url(runtime: Runtime) -> RunState:
    """Run the minimal pipeline for one ``--url`` job and return the final state."""
    runtime.out(LIVE_RUN_NOTICE if not runtime.dry_run else DRY_RUN_NOTICE)
    graph = build_graph(runtime)
    final: RunState = graph.invoke({"job_url": runtime.job_url, "dry_run": runtime.dry_run})
    return final
