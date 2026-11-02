"""Task 8: wait for the human's submission, then open the next job and repeat.

Tasks 2-4 fill one job to its terminal step (only **Submit application** remains)
and leave the browser open. This module owns the two browser-side pieces of the
Task 8 loop:

1. :func:`await_human_submit` — with the form open on the terminal step, poll the
   page until the human **submits** the application, closes the browser, or the
   wait times out. The agent **never** clicks **Submit application**; it only
   observes the result. A dismissed modal (X) or a closed window without a
   submission confirmation is **not** a submission. Once the submission is seen,
   any post-apply dialog (the "Your application was sent to X!" confirmation and
   the "Turn your resume into a profile" promo) is closed with a safe dismiss
   control — **Not now** (or the X / **Done**) — never **Update profile**.
2. :func:`open_next_job` — back on the results list, re-read the cards, skip the
   ones already marked **"Applied"** (Task 6), paginate when a whole page is
   Applied (Task 7), and **select** the first unapplied **Easy Apply** job, reading
   its description (Task 3) so the loop can match a resume. Easy Apply is clicked
   only after that match (Task 16).

The graph nodes that drive the loop live in :mod:`src.nodes.apply_loop`; the
per-job human-submit timeout/poll settings are reused
(``AUTOJOB_SESSION_KEEP_OPEN_TIMEOUT_SECONDS`` / ``..._POLL_SECONDS``). The
submission probe and its pure rules live in
:mod:`src.tools.linkedin_submission` and are re-exported here.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

from src.configuration import Settings, load_settings
from src.state import JobDescription, Task2Outcome
from src.tools.browser import (
    _first_element,
    _safe,
    close_run,
    forget_run,
    get_run,
    run_is_connected,
)
from src.tools.linkedin_date_posted import PAST_WEEK_VALUE
from src.tools.linkedin_job_selection import _job_key, _task2_on_page
from src.tools.linkedin_resume_gate import close_easy_apply_form
from src.tools.linkedin_status_overlay import begin_human_turn, emit_step, end_human_turn
from src.tools.linkedin_submission import (
    is_dismiss_label,
    looks_like_submission,
    read_submission_state,
    submission_detected,
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


# How many dismiss clicks to attempt (a second dialog, e.g. the promo, can appear
# after the confirmation closes).
_MAX_DISMISS_PASSES = 3


async def _dismiss_confirmation(page, state: dict, title: str = "") -> None:
    """Click a safe "Not now"/"Done"/dismiss control to reveal the results list.

    LinkedIn's post-apply dialog confirms the submission ("Your application was
    sent to <company>!") and sometimes also offers a "Turn your resume into a
    profile" promo. It is closed with **Not now** (or the X / **Done**), never
    with **Update profile**: this only clicks a control whose label is an exact
    dismiss label (:func:`is_dismiss_label`). Waits briefly and repeats so a
    second dialog that appears after the first also closes (best effort).
    """
    for _ in range(_MAX_DISMISS_PASSES):
        marker = state.get("done_marker")
        if not marker:
            return
        element = await _first_element(page, [f'[data-autojob-done="{marker}"]'])
        if element is None:
            return
        await _safe(element.click())
        await asyncio.sleep(0.5)
        state = await _read_state(page, title) or {}


async def dismiss_post_apply_modals(page, title: str = "") -> None:
    """Close a post-apply dialog still covering the results list (best effort).

    LinkedIn can leave the "Your application was sent to X!" / "Turn your resume
    into a profile" dialog on the results page after a submission. Its backdrop
    would block the next job's click, so dismiss it before re-reading the cards.
    Only dialog-closing controls are clicked (never **Update profile**); see
    :func:`is_dismiss_label`.
    """
    state = await _read_state(page, title)
    if state is None:
        return
    await _dismiss_confirmation(page, state, title)


# A live CDP link can die while a ``page.evaluate`` is in flight (the human closed
# the window); browser-use's call then never returns, so the wait hung instead of
# ending. Bound every read, and give up after a few in a row (BUG-061).
_READ_TIMEOUT_SECONDS = 15.0
_MAX_UNRESPONSIVE_READS = 3


async def _read_state(page, title: str, company: str = "") -> dict | None:
    """Read the submission state, or ``None`` when the page stops answering."""
    try:
        return await asyncio.wait_for(
            read_submission_state(page, title, company), _READ_TIMEOUT_SECONDS
        )
    except Exception:  # noqa: BLE001 - a dead CDP link must never hang the wait
        return None


async def _await_human_submit(
    run_id: str | None,
    settings: Settings | None = None,
    progress=None,
    title: str = "",
    company: str = "",
) -> str:
    """Wait for the human to submit the open application (the agent never does).

    ``title``/``company`` identify the open job's results card, so the card
    fallback only trusts that job flipping to **Applied**. Returns
    ``"submitted"`` once a submission is confirmed, ``"closed"`` when the human
    closes the browser, or ``"timeout"`` when the wait
    (``AUTOJOB_SESSION_KEEP_OPEN_TIMEOUT_SECONDS``; ``0`` waits indefinitely)
    elapses — in which case the browser is **left open** for the human (the agent
    never closes it). Never clicks **Submit application**.
    """
    settings = settings or load_settings()
    notify = progress or (lambda _message: None)
    run = get_run(run_id)
    if run is None:
        return "closed"

    timeout = settings.session.keep_open_timeout_seconds
    poll = settings.session.keep_open_poll_seconds
    notify(
        "Task 8: waiting for you to submit this application yourself "
        "(the agent never clicks Submit). Submit it, or close the browser to stop."
    )
    emit_step(
        notify,
        "Waiting for you - submit this application yourself, then close the window.",
    )
    deadline = None if timeout <= 0 else time.monotonic() + timeout
    # The card's "Applied" badge and the pane's "Application submitted" status are
    # only evidence of this submission when they flip during the wait. A card or
    # status that already read applied/submitted at the start (a stale value, or a
    # job applied in an earlier run) must not make a dismissed form look like a
    # submission. The card match uses the title line (and company when known), so a
    # differently titled card is never mistaken for this job (BUG-060).
    initial = await _read_state(run.page, title, company)
    if initial is None:
        # The page never answered: the CDP link is gone. End the wait instead of
        # hanging on a dead browser (BUG-061).
        forget_run(run_id)
        return "closed"
    baseline = _normalize(initial["confirmation"])
    if baseline:
        # A confirmation already on screen when this wait starts belongs to the
        # previous job (its dialog stayed open on the results page). Dismiss it
        # and ignore that exact text; only a *new* confirmation counts — otherwise
        # the loop could "detect" a submission the human never made and open the
        # next job by itself.
        await _dismiss_confirmation(run.page, initial, title)
        initial = await _read_state(run.page, title, company) or initial
        baseline = _normalize(initial["confirmation"])
    already_applied = bool(initial.get("card_applied"))
    already_submitted = bool(initial.get("status_submitted"))
    unresponsive = 0
    while True:
        if not run_is_connected(run_id):
            forget_run(run_id)
            return "closed"
        state = await _read_state(run.page, title, company)
        if state is None:
            unresponsive += 1
            if not run_is_connected(run_id) or unresponsive >= _MAX_UNRESPONSIVE_READS:
                forget_run(run_id)
                return "closed"
            await asyncio.sleep(poll)
            continue
        unresponsive = 0
        confirmation = state["confirmation"]
        if baseline and _normalize(confirmation) == baseline:
            confirmation = ""  # the stale dialog from the previous job
        if submission_detected(
            confirmation=confirmation,
            form_open=state["form_open"],
            card_applied=state["card_applied"],
            card_was_applied=already_applied,
            status_submitted=state["status_submitted"],
            status_was_submitted=already_submitted,
        ):
            notify("Task 8: submission detected.")
            emit_step(notify, "Submission detected - looking for the next job.")
            await _dismiss_confirmation(run.page, state, title)
            return "submitted"
        if deadline is not None and time.monotonic() >= deadline:
            notify(
                "Task 8: no submission detected before the wait ended; leaving the browser open."
            )
            try:
                await asyncio.wait_for(close_run(run_id), _READ_TIMEOUT_SECONDS)
            except Exception:  # noqa: BLE001 - a dead CDP link must not hang here
                forget_run(run_id)
            return "timeout"
        await asyncio.sleep(poll)


@dataclass
class NextJobResult:
    """The outcome of looking for the next unapplied job after a submission."""

    opened: bool = False
    task2: Task2Outcome = field(default_factory=Task2Outcome)
    description: JobDescription = field(default_factory=JobDescription)
    reason: str = ""


def _no_job_reason(task2: Task2Outcome) -> str:
    """Why Task 2 opened no job on this pass (a clear, human-readable note)."""
    # Task 17: when the scan fell back to the other range, the applied counts no
    # longer describe the whole search; say both ranges were exhausted instead of
    # the misleading "every job is Applied".
    if task2.date_range_fallback_used:
        if task2.date_range_preferred == PAST_WEEK_VALUE:
            return task2.notes or (
                "no unapplied Easy Apply job remains in the past week or the past 24 hours"
            )
        return task2.notes or (
            "no unapplied Easy Apply job remains in the past 24 hours or the past week"
        )
    if task2.date_range_used == PAST_WEEK_VALUE:
        return task2.notes or "no unapplied Easy Apply job remains in the past week"
    if task2.jobs_seen and task2.applied_jobs_skipped >= task2.jobs_seen:
        return "every job on every results page is already Applied"
    return task2.notes or "no unapplied Easy Apply job could be opened"


async def open_next_job(
    run_id: str | None,
    settings: Settings | None = None,
    progress=None,
    skip_title: str = "",
    skip_titles: Iterable[str] = (),
    close_form: bool = False,
    date_range: str = "",
    preferred_range: str = "",
    skip_job_ids: Iterable[str] = (),
    results_url: str = "",
) -> NextJobResult:
    """Select the next unapplied Easy Apply job on the open results list.

    Reuses Task 2's match-first selection (which skips **"Applied"** cards, Task 6,
    paginates whole Applied pages, Task 7, and widens an exhausted 24-hour list to
    Past week, Task 17) and Task 3's description read. The Easy Apply button is
    **not** clicked here; the graph's ``open_form`` node does that only after a
    resume match. The jobs named by ``skip_title`` (the one just handled) and every
    accumulated ``skip_titles`` entry (Task 16 skips) are never re-opened, even if
    their cards have not flipped to **"Applied"**. When nothing can be selected,
    ``reason`` explains why and ``opened`` is ``False``.

    ``date_range`` is the range the previous scan finished on. ``preferred_range``
    is the range the user chose at startup, so the fallback direction stays
    correct (Past 24 hours ⇄ Past week). A run already on the fallback range keeps
    scanning that range instead of bouncing back to the primary one.

    ``close_form`` closes a form left open by a self-healed retry before re-reading
    the results list. A normal Task 16 skip never opens a form, so this is a no-op
    there; after a human submission the form is already gone.
    """
    from src.tools.linkedin_best_matching_resume import read_job_description  # keep light

    settings = settings or load_settings()
    notify = progress or (lambda _message: None)
    run = get_run(run_id)
    if run is None:
        return NextJobResult(
            task2=Task2Outcome(notes="browser session is no longer available"),
            reason="browser session is no longer available",
        )

    titles = [title for title in (skip_title, *skip_titles) if (title or "").strip()]
    skip_keys = {_job_key(title, -1) for title in titles}
    skip_keys.update(f"job:{identity}" for identity in skip_job_ids if str(identity).isdigit())
    emit_step(notify, "Please wait - opening the next unapplied job...")
    # The post-apply "Your application was sent..." / "Turn your resume into a
    # profile" dialog can still cover the results list; its backdrop would block
    # the next card's click, so dismiss it (Not now) before re-reading the cards.
    await dismiss_post_apply_modals(run.page, skip_title)
    if close_form and not await close_easy_apply_form(run.page, settings, notify):
        return NextJobResult(
            task2=Task2Outcome(notes="the Easy Apply form could not be closed"),
            reason="the Easy Apply form could not be closed",
        )
    if skip_job_ids and results_url:
        from src.tools.linkedin_validation.continuation import prepare_results_page

        await prepare_results_page(run.page, results_url, notify)
    scan_kwargs: dict = {
        "skip_keys": skip_keys,
        "capture": read_job_description,
        "open_form": False,
        "date_range": date_range,
    }
    if preferred_range:
        scan_kwargs["preferred_range"] = preferred_range
    task2 = await _task2_on_page(run.page, settings, notify, **scan_kwargs)
    if task2.job_selected or (task2.easy_apply_clicked and task2.application_form_opened):
        # Task 2 read the description while the job was open (before Easy Apply);
        # only re-read if that produced nothing. The form stays closed until the
        # resume match selects this job (Task 16's open_form node).
        description = task2.job_description or JobDescription()
        if not description.is_read:
            emit_step(notify, "Please wait - reading the job description...")
            description = await read_job_description(run.page)
        return NextJobResult(opened=True, task2=task2, description=description)
    return NextJobResult(task2=task2, reason=_no_job_reason(task2))


async def await_human_submit(
    run_id: str | None,
    settings: Settings | None = None,
    progress=None,
    title: str = "",
    company: str = "",
) -> str:
    """Task 8 wait with the page unlocked for the human's submit click."""
    run = get_run(run_id)
    page = run.page if run is not None else None
    await begin_human_turn(page)
    try:
        return await _await_human_submit(
            run_id, settings, progress=progress, title=title, company=company
        )
    finally:
        await end_human_turn(page)


__all__ = [
    "NextJobResult",
    "await_human_submit",
    "dismiss_post_apply_modals",
    "is_dismiss_label",
    "looks_like_submission",
    "open_next_job",
    "read_submission_state",
    "submission_detected",
]
