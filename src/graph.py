"""The StateGraph builder and compiler.

``langgraph.json`` points at ``build_graph`` in this module. The pipeline has the
same shape (read → answer → fill → review) but is
async, because browser-use is asyncio-native. Completion (full loop, checkpointing,
crash resume) is Task 15.

Browser, database and settings dependencies are injected through :class:`Runtime`;
the no-argument studio entry point is completed in Task 15.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

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
    """Everything the graph needs, injected once per run."""

    settings: AppSettings
    conn: sqlite3.Connection
    browser: Any
    llm: Any
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
# Nodes — thin async functions over RunState; all I/O lives in src/tools and nodes
# ---------------------------------------------------------------------------


async def _node_discover(runtime: Runtime, state: RunState) -> RunState:
    job = await discover.read_job(
        runtime.browser, runtime.llm, state["job_url"], guard=runtime.guard
    )
    runtime.out(f"Read job: {job.get('title', '')} at {job.get('company', '')}")
    store.upsert_job(
        runtime.conn,
        store.Job(
            job_id=job["job_id"],
            title=job.get("title", ""),
            company=job.get("company", ""),
            description=job.get("description", ""),
            url=job.get("url", ""),
            status=store.JobStatus.SEEN,
        ),
    )
    return {"job": job}


async def _node_answer(runtime: Runtime, state: RunState) -> RunState:
    """Read the real form fields with the agent, then answer them with the rules."""
    job_id = state["job"]["job_id"]
    try:
        labels = await fill.open_and_read_fields(runtime.browser, runtime.llm, runtime.guard)
        answers = answering.answer_fields(labels, runtime.facts)
    except Exception:
        # A field-read failure is a failed application, not a silent blank form —
        # mirror _node_fill so the job never sits at `seen` with no signal.
        store.set_job_status(runtime.conn, job_id, store.JobStatus.FAILED)
        raise
    job: JobState = {**state["job"], "answers": list(answers)}
    return {"job": job, "answer_map": {answer.field: answer for answer in answers}}


async def _node_fill(runtime: Runtime, state: RunState) -> RunState:
    job = state["job"]
    job_id = job["job_id"]
    try:
        report = await fill.fill_application(
            runtime.browser,
            runtime.llm,
            runtime.guard,
            job,
            job.get("answers", []),
            resume_path=runtime.resume_path,
            artifacts_dir=runtime.settings.paths.artifacts,
        )
    except Exception:
        store.set_job_status(runtime.conn, job_id, store.JobStatus.FAILED)
        raise

    # Review must show every field: the answers actually filled, plus a
    # NEEDS_REVIEW entry for each control left blank (never guessed).
    review_answers: list[store.Answer] = list(report.filled)
    for label in report.flagged:
        review_answers.append(
            store.Answer(
                field=label.strip() or "(unnamed field)",
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


async def _node_review(runtime: Runtime, state: RunState) -> RunState:
    job = state["job"]
    submit = (
        None
        if runtime.dry_run
        else partial(
            fill.submit_application, runtime.browser, runtime.llm, runtime.guard, job
        )
    )
    result = await review.review_application(
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
            "build_graph needs a Runtime in Task 8/17; the studio entry point is "
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


async def run_single_url(runtime: Runtime) -> RunState:
    """Run the pipeline for one ``--url`` job and return the final state."""
    runtime.out(LIVE_RUN_NOTICE if not runtime.dry_run else DRY_RUN_NOTICE)
    graph = build_graph(runtime)
    final: RunState = await graph.ainvoke(
        {"job_url": runtime.job_url, "dry_run": runtime.dry_run}
    )
    return final
