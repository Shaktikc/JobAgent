"""Task 3 main flow: describe the pool, let the LLM pick, else fall back.

Task 3.2 describes every resume in the pool and asks the LLM to choose the single
best match (or **none**). Task 3.1 handles **none**: reuse a resume remembered for
a similar job; otherwise ask the human in the browser, store the uploaded file in
the pool, describe it, and use it directly. Resume files are never modified.
"""

from __future__ import annotations

import time
from pathlib import Path

from src.configuration import Settings
from src.state import JobDescription, ResumeCandidate, Task3Outcome
from src.tools.browser import _append_note
from src.tools.linkedin_status_overlay import emit_llm, emit_step
from src.tools.resume_descriptions import (
    ResumeDescriptionError,
    describe_resume,
    described_candidates,
    ensure_descriptions,
    load_descriptions,
    pick_best_resume,
    store_description,
)
from src.tools.resume_library import (
    find_reusable_resume,
    load_library,
    remember_resume,
    store_uploaded_resume,
)

from .resume_prompt import ask_human_for_resume
from .resume_text import list_resume_files


async def ensure_resume(
    description: JobDescription,
    resumes_dir: str | Path,
    settings: Settings,
    page=None,
    notify=None,
    asker=None,
    describer=None,
    matcher=None,
) -> Task3Outcome:
    """Select the best resume, falling back to the human when nothing matches.

    Task 3.2: every resume in the pool is described by the **LLM**, then the LLM
    chooses the single best match (or **none**). Task 3.1: when the LLM answers
    **none**, reuse a resume already remembered for a similar job; otherwise ask
    the human for one in the browser, store it in the pool, have the **LLM**
    describe it, and use it directly. ``asker``/``describer``/``matcher`` are
    injectable for tests.
    """
    notify = notify or (lambda _message: None)
    files = list_resume_files(resumes_dir)
    outcome = Task3Outcome(
        job_description=description,
        resumes_dir=str(resumes_dir),
        resumes_found=len(files),
    )
    store_path = settings.resume_descriptions_file
    job_label = description.title.strip() or "this job"
    emit_step(
        notify,
        f"Please wait - choosing the best resume for {job_label!r} "
        f"from {len(files)} resume(s)...",
    )
    described_count = {"n": 0}

    async def _describe_with_status(path):
        described_count["n"] += 1
        emit_llm(
            notify,
            f"summarizing resume {Path(path).name!r} "
            f"({described_count['n']} of {len(files)})...",
        )
        started = time.monotonic()
        description = await describe_resume(path, settings)
        elapsed = time.monotonic() - started
        emit_llm(
            notify,
            f"described resume {Path(path).name!r} in {elapsed:.1f}s",
            description.summary or "(no summary)",
        )
        return description

    describe = describer or _describe_with_status
    pick = matcher or (lambda job, candidates: pick_best_resume(job, candidates, settings))

    # Task 3.2: describe every resume, then let the LLM choose (no fallback).
    try:
        await ensure_descriptions(
            resumes_dir, store_path, settings, files=files, describe=describe
        )
        candidates = described_candidates(files, load_descriptions(store_path))
    except ResumeDescriptionError as exc:
        outcome.error = f"match: {exc}"
        outcome.notes = _append_note(outcome.notes, "could not describe the resume pool")
        notify(f"Task 3.2: {exc}")
        return outcome

    for path, candidate in candidates:
        outcome.candidates.append(
            ResumeCandidate(path=path, summary=candidate.summary, described=True)
        )

    emit_llm(
        notify,
        f"choosing the best-matching resume for {job_label!r} "
        f"from {len(candidates)} resume(s)...",
    )
    started = time.monotonic()
    try:
        result = await pick(description, candidates)
    except ResumeDescriptionError as exc:
        outcome.error = f"match: {exc}"
        outcome.notes = _append_note(outcome.notes, "the LLM could not choose a resume")
        notify(f"Task 3.2: {exc}")
        emit_llm(notify, f"could not choose a resume for {job_label!r}", str(exc))
        return outcome
    elapsed = time.monotonic() - started
    emit_llm(
        notify,
        f"the LLM answered in {elapsed:.1f}s",
        f"chosen resume for {job_label!r}",
    )

    if result.selected_path:
        outcome.selected_path = result.selected_path
        outcome.rationale = result.rationale or "the LLM chose the best-matching resume"
        outcome.notes = _append_note(outcome.notes, "the LLM chose the best-matching resume")
        emit_llm(
            notify,
            f"chose resume {Path(result.selected_path).name!r} for {job_label!r}",
            result.rationale,
        )
        return outcome

    # No resume matched the job: hand off to Task 3.1.
    outcome.no_match = True
    outcome.rationale = result.rationale or "the LLM found no matching resume"
    emit_llm(notify, f"no resume matched {job_label!r}", result.rationale)
    reusable = find_reusable_resume(
        load_library(settings.resume_library_file), description, resumes_dir
    )
    if reusable:
        outcome.selected_path = reusable
        outcome.reused_from_library = reusable
        outcome.rationale = (
            f"no resume matched, but {Path(reusable).name!r} was remembered for a similar job"
        )
        outcome.notes = _append_note(outcome.notes, f"reused the remembered resume {reusable!r}")
        notify(f"Task 3.1: reusing {Path(reusable).name!r} from a similar job.")
        return outcome

    if page is None or not settings.session.ask_human:
        outcome.notes = _append_note(
            outcome.notes, "no resume matched and asking the human is unavailable"
        )
        return outcome

    outcome.asked_human = True
    provided = await (asker or ask_human_for_resume)(page, settings, notify)
    if provided is None:
        outcome.notes = _append_note(outcome.notes, "the human did not provide a resume")
        return outcome

    filename, content = provided
    try:
        stored = store_uploaded_resume(resumes_dir, filename, content)
    except ValueError as exc:
        outcome.notes = _append_note(outcome.notes, f"could not store the uploaded resume: {exc}")
        return outcome

    # Task 3.2: describe the uploaded resume before it is used (no fallback).
    try:
        uploaded = await describe(stored)
    except ResumeDescriptionError as exc:
        outcome.error = f"match: {exc}"
        outcome.notes = _append_note(outcome.notes, "the uploaded resume could not be described")
        notify(f"Task 3.2: {exc}")
        return outcome

    store_description(store_path, stored, uploaded)
    remember_resume(settings.resume_library_file, description, str(stored))
    outcome.human_resume_path = str(stored)
    outcome.selected_path = str(stored)
    outcome.rationale = f"human-provided resume {stored.name!r} for a job nothing matched"
    outcome.resumes_found = len(list_resume_files(resumes_dir))
    outcome.candidates.append(
        ResumeCandidate(path=str(stored), summary=uploaded.summary, described=True)
    )
    outcome.notes = _append_note(
        outcome.notes, f"stored, described and remembered the uploaded resume {stored!r}"
    )
    notify(f"Task 3.1: stored {stored.name!r}, described it, and remembered it for similar jobs.")
    return outcome


__all__ = ["ensure_resume"]
