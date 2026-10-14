"""Task 8: wait for the human's submission, then open the next job and repeat.

Tasks 2-4 fill one job to its terminal step (only **Submit application** remains)
and leave the browser open. This module owns the two browser-side pieces of the
Task 8 loop:

1. :func:`await_human_submit` — with the form open on the terminal step, poll the
   page until the human **submits** the application, closes the browser, or the
   wait times out. The agent **never** clicks **Submit application**; it only
   observes the result. A dismissed modal (X) or a closed window without a
   submission confirmation is **not** a submission.
2. :func:`open_next_job` — back on the results list, re-read the cards, skip the
   ones already marked **"Applied"** (Task 6), paginate when a whole page is
   Applied (Task 7), and open the first unapplied **Easy Apply** job, reading its
   description (Task 3) so the loop can match a resume and fill it again.

The graph nodes that drive the loop live in :mod:`src.nodes.apply_loop`; the
per-job human-submit timeout/poll settings are reused
(``AUTOJOB_SESSION_KEEP_OPEN_TIMEOUT_SECONDS`` / ``..._POLL_SECONDS``).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field

from src.configuration import Settings, load_settings
from src.state import JobDescription, Task2Outcome
from src.tools.browser import (
    FIND_APPLY_ROOT_JS,
    _first_element,
    _loads,
    _safe,
    close_run,
    forget_run,
    get_run,
    run_is_connected,
)
from src.tools.linkedin_job_selection import _job_key, _task2_on_page

# Phrases that confirm the human's application was sent. LinkedIn's confirmation
# copy varies, so match any of these in a visible dialog.
_SUBMISSION_HINTS = (
    "application sent",
    "application was sent",
    "application submitted",
    "application has been submitted",
    "application received",
    "you've applied",
    "you have applied",
    "successfully applied",
    "you applied",
)

# Phrases that mean "close this confirmation" — safe to click (never Submit).
_DISMISS_HINTS = ("done", "dismiss", "close", "got it")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def looks_like_submission(text: str) -> bool:
    """True when ``text`` is a post-submit confirmation (not a dismissed modal)."""
    normalized = _normalize(text)
    return any(hint in normalized for hint in _SUBMISSION_HINTS)


def submission_detected(*, confirmation: str, form_open: bool, card_applied: bool) -> bool:
    """Decide whether the human's submission is confirmed.

    The confirmation dialog is the strong signal. As a fallback (for a human who
    dismisses the confirmation before the next poll), the Easy Apply form being
    closed **and** the open job's card now reading **"Applied"** also counts — a
    card only flips to Applied after a real submit, so an X-dismissed form does
    not trigger it.
    """
    if looks_like_submission(confirmation):
        return True
    return card_applied and not form_open


# Probe the page for a submission confirmation. ``__JOB_TITLE__`` is replaced with
# a JSON string literal of the open job's title, so the card fallback can match
# the job's own results card rather than any card on the page.
_SUBMISSION_QUERY_TEMPLATE = (
    "() => {\n"
    + FIND_APPLY_ROOT_JS
    + "\n"
    + r"""
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => !!el && el.getClientRects().length > 0;
  const form = findApplyRoot();

  const confirmRe = new RegExp(
    "application sent|application was sent|application submitted|"
    + "application has been submitted|application received|"
    + "you(?:'ve| have) applied|successfully applied|you applied", "i"
  );
  let confirmation = '';
  let doneMarker = '';
  let i = 0;
  const dialogs = Array.from(document.querySelectorAll(
    'div[role="dialog"], .artdeco-modal, div[data-test-modal-container], '
    + '.artdeco-modal--layer-default'
  )).filter(visible);
  dialogs.forEach((dialog) => {
    const text = norm(dialog.innerText);
    if (!confirmRe.test(text)) return;
    if (!confirmation) confirmation = text.slice(0, 500);
    if (doneMarker) return;
    dialog.querySelectorAll('button, [role="button"]').forEach((b) => {
      if (doneMarker) return;
      const label = norm(b.innerText) || norm(b.getAttribute('aria-label'));
      if (/^(done|dismiss|close|got it)$/i.test(label)) {
        const marker = 'd' + (i++);
        b.setAttribute('data-autojob-done', marker);
        doneMarker = marker;
      }
    });
  });

  // Fallback: the open job's own results card now reads "Applied".
  const wanted = norm(__JOB_TITLE__).toLowerCase();
  let cardApplied = false;
  if (wanted) {
    const cards = Array.from(document.querySelectorAll(
      'li.jobs-search-results__list-item, li.scaffold-layout__list-item, '
      + 'div.job-card-container, div.jobs-search-results-list__list-item, '
      + 'ul.jobs-search__results-list > li, [data-autojob-card]'
    ));
    const card = cards.find((c) => norm(c.innerText).toLowerCase().includes(wanted));
    if (card) cardApplied = /(^|\s)applied(\s|·|$)/i.test(norm(card.innerText));
  }

  return JSON.stringify({
    form_open: !!form,
    confirmation: confirmation,
    card_applied: cardApplied,
    done_marker: doneMarker
  });
}
"""
)


def _submission_query(title: str) -> str:
    """Build the submission probe with the open job's title embedded safely."""
    return _SUBMISSION_QUERY_TEMPLATE.replace("__JOB_TITLE__", json.dumps(title or ""))


async def read_submission_state(page, title: str = "") -> dict:
    """Return the page's submission signals for the open job (see the probe)."""
    payload = _loads(await _safe(page.evaluate(_submission_query(title)), ""))
    return {
        "form_open": bool(payload.get("form_open")),
        "confirmation": str(payload.get("confirmation") or ""),
        "card_applied": bool(payload.get("card_applied")),
        "done_marker": str(payload.get("done_marker") or ""),
    }


async def _dismiss_confirmation(page, state: dict) -> None:
    """Click a safe "Done"/dismiss control to reveal the results list (best effort)."""
    marker = state.get("done_marker")
    if not marker:
        return
    element = await _first_element(page, [f'[data-autojob-done="{marker}"]'])
    if element is None:
        return
    await _safe(element.click())
    await asyncio.sleep(0.5)


async def await_human_submit(
    run_id: str | None,
    settings: Settings | None = None,
    progress=None,
    title: str = "",
) -> str:
    """Wait for the human to submit the open application (the agent never does).

    Returns ``"submitted"`` once a submission is confirmed, ``"closed"`` when the
    human closes the browser, or ``"timeout"`` when the wait
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
    deadline = None if timeout <= 0 else time.monotonic() + timeout
    while True:
        if not run_is_connected(run_id):
            forget_run(run_id)
            return "closed"
        state = await read_submission_state(run.page, title)
        if submission_detected(
            confirmation=state["confirmation"],
            form_open=state["form_open"],
            card_applied=state["card_applied"],
        ):
            notify("Task 8: submission detected.")
            await _dismiss_confirmation(run.page, state)
            return "submitted"
        if deadline is not None and time.monotonic() >= deadline:
            notify(
                "Task 8: no submission detected before the wait ended; "
                "leaving the browser open."
            )
            await close_run(run_id)
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
    if task2.jobs_seen and task2.applied_jobs_skipped >= task2.jobs_seen:
        return "every job on every results page is already Applied"
    return task2.notes or "no unapplied Easy Apply job could be opened"


async def open_next_job(
    run_id: str | None,
    settings: Settings | None = None,
    progress=None,
    skip_title: str = "",
) -> NextJobResult:
    """Open the next unapplied Easy Apply job on the open results list.

    Reuses Task 2's selection (which skips **"Applied"** cards, Task 6, and
    paginates whole Applied pages, Task 7) and Task 3's description read. The job
    named by ``skip_title`` (the one the human just submitted) is never re-opened,
    even if its card has not yet flipped to **"Applied"**. When nothing can be
    opened, ``reason`` explains why and ``opened`` is ``False``.
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

    skip_keys = {_job_key(skip_title, -1)} if skip_title else set()
    task2 = await _task2_on_page(
        run.page, settings, notify, skip_keys=skip_keys, capture=read_job_description
    )
    if task2.easy_apply_clicked and task2.application_form_opened:
        # Task 2 read the description while the job was open (before Easy Apply);
        # only re-read if that produced nothing.
        description = task2.job_description or JobDescription()
        if not description.is_read:
            description = await read_job_description(run.page)
        return NextJobResult(opened=True, task2=task2, description=description)
    return NextJobResult(task2=task2, reason=_no_job_reason(task2))


__all__ = [
    "NextJobResult",
    "await_human_submit",
    "looks_like_submission",
    "open_next_job",
    "read_submission_state",
    "submission_detected",
]
