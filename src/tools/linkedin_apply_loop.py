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
from src.tools.linkedin_status_overlay import emit_step

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

# Exact button labels that only close a dialog — safe to click (never Submit, and
# never the promo's "Update profile"). "Not now" is the decline button on
# LinkedIn's newer post-apply dialog ("Your application was sent to X!" / "Turn
# your resume into a profile that recruiters notice"); the older confirmation
# offers "Done"/the X. Keep in sync with the regex in ``_SUBMISSION_QUERY_TEMPLATE``.
_DISMISS_HINTS = (
    "done",
    "dismiss",
    "close",
    "got it",
    "not now",
    "no thanks",
    "maybe later",
    "skip",
)

_DISMISS_RE = re.compile(r"^(?:" + "|".join(map(re.escape, _DISMISS_HINTS)) + r")$")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def is_dismiss_label(label: str) -> bool:
    """True for a control that only closes a dialog (never submits or applies).

    The post-apply promo ("Turn your resume into a profile that recruiters
    notice") offers **Not now** and **Update profile**; only the former matches,
    so the agent can never click the profile-editing call to action.
    """
    return bool(_DISMISS_RE.match(_normalize(label)))


def looks_like_submission(text: str) -> bool:
    """True when ``text`` is a post-submit confirmation (not a dismissed modal)."""
    normalized = _normalize(text)
    return any(hint in normalized for hint in _SUBMISSION_HINTS)


def submission_detected(
    *,
    confirmation: str,
    form_open: bool,
    card_applied: bool,
    card_was_applied: bool = False,
) -> bool:
    """Decide whether the human's submission is confirmed.

    The confirmation dialog is the strong signal. As a fallback (for a human who
    dismisses the confirmation before the next poll), the Easy Apply form being
    closed **and** the open job's card now reading **"Applied"** also counts — a
    card only flips to Applied after a real submit, so an X-dismissed form does
    not trigger it. ``card_was_applied`` guards the stale case: a card that
    already read Applied before the wait is not evidence of a submission now.
    """
    if looks_like_submission(confirmation):
        return True
    if card_was_applied:
        return False
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
  // Keep in sync with _DISMISS_HINTS in this module. Never add "Update profile":
  // the post-apply promo offers that alongside "Not now", and clicking it would
  // edit the human's profile.
  const dismissRe = /^(done|dismiss|close|got it|not now|no thanks|maybe later|skip)$/i;
  const preferRe = /^(not now|no thanks|maybe later|skip)$/i;
  const dialogs = Array.from(document.querySelectorAll(
    'div[role="dialog"], .artdeco-modal, div[data-test-modal-container], '
    + '.artdeco-modal--layer-default'
  )).filter(visible);
  dialogs.forEach((dialog) => {
    const text = norm(dialog.innerText);
    if (!confirmRe.test(text)) return;
    if (!confirmation) confirmation = text.slice(0, 500);
    if (doneMarker) return;
    // Prefer an explicit "Not now" style decline over the X/Done; match labels
    // exactly so the promo's "Update profile" is never picked.
    const buttons = Array.from(dialog.querySelectorAll('button, [role="button"]'));
    const labels = buttons.map(
      (b) => norm(b.innerText) || norm(b.getAttribute('aria-label'))
    );
    let pick = labels.findIndex((label) => preferRe.test(label));
    if (pick < 0) pick = labels.findIndex((label) => dismissRe.test(label));
    if (pick < 0) return;
    const marker = 'd' + (i++);
    buttons[pick].setAttribute('data-autojob-done', marker);
    doneMarker = marker;
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
        state = await read_submission_state(page, title)


async def dismiss_post_apply_modals(page, title: str = "") -> None:
    """Close a post-apply dialog still covering the results list (best effort).

    LinkedIn can leave the "Your application was sent to X!" / "Turn your resume
    into a profile" dialog on the results page after a submission. Its backdrop
    would block the next job's click, so dismiss it before re-reading the cards.
    Only dialog-closing controls are clicked (never **Update profile**); see
    :func:`is_dismiss_label`.
    """
    try:
        state = await read_submission_state(page, title)
    except Exception:  # noqa: BLE001 - best-effort cleanup of a stale dialog
        return
    await _dismiss_confirmation(page, state, title)


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
    emit_step(
        notify,
        "Waiting for you - submit this application yourself, then close the window.",
    )
    deadline = None if timeout <= 0 else time.monotonic() + timeout
    # The card's "Applied" badge is only evidence of *this* submission when it
    # flips from unapplied to Applied during the wait. A card that already read
    # Applied at the start (a stale status the scan let through, or a job applied
    # in an earlier run) must not make a dismissed form look like a submission —
    # that advanced the loop and opened the next job without the human submitting.
    initial = await read_submission_state(run.page, title)
    baseline = _normalize(initial["confirmation"])
    if baseline:
        # A confirmation already on screen when this wait starts belongs to the
        # previous job (its dialog stayed open on the results page). Dismiss it
        # and ignore that exact text; only a *new* confirmation counts — otherwise
        # the loop could "detect" a submission the human never made and open the
        # next job by itself.
        await _dismiss_confirmation(run.page, initial, title)
        initial = await read_submission_state(run.page, title)
        baseline = _normalize(initial["confirmation"])
    already_applied = bool(initial.get("card_applied"))
    while True:
        if not run_is_connected(run_id):
            forget_run(run_id)
            return "closed"
        state = await read_submission_state(run.page, title)
        confirmation = state["confirmation"]
        if baseline and _normalize(confirmation) == baseline:
            confirmation = ""  # the stale dialog from the previous job
        if submission_detected(
            confirmation=confirmation,
            form_open=state["form_open"],
            card_applied=state["card_applied"],
            card_was_applied=already_applied,
        ):
            notify("Task 8: submission detected.")
            emit_step(notify, "Submission detected - looking for the next job.")
            await _dismiss_confirmation(run.page, state, title)
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
    emit_step(notify, "Please wait - opening the next unapplied job...")
    # The post-apply "Your application was sent..." / "Turn your resume into a
    # profile" dialog can still cover the results list; its backdrop would block
    # the next card's click, so dismiss it (Not now) before re-reading the cards.
    await dismiss_post_apply_modals(run.page, skip_title)
    task2 = await _task2_on_page(
        run.page, settings, notify, skip_keys=skip_keys, capture=read_job_description
    )
    if task2.easy_apply_clicked and task2.application_form_opened:
        # Task 2 read the description while the job was open (before Easy Apply);
        # only re-read if that produced nothing.
        description = task2.job_description or JobDescription()
        if not description.is_read:
            emit_step(notify, "Please wait - reading the job description...")
            description = await read_job_description(run.page)
        return NextJobResult(opened=True, task2=task2, description=description)
    return NextJobResult(task2=task2, reason=_no_job_reason(task2))


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
