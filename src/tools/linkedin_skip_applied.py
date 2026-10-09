"""Task 6: skip jobs already marked "Applied" and open the next unapplied job.

This module owns Task 6's applied-job detection, split out of
:mod:`src.tools.linkedin_job_selection` (and :mod:`src.tools.linkedin`):

1. Classify a job card as already applied from its status text (the word
   **Applied**), ignoring the age text ("5 months ago") and other statuses
   ("Viewed", "Saved") as well as an "Easy Apply" badge.
2. Record each skipped applied card (index/title) on the Task 2 outcome and emit
   a log line, without clicking the card.
3. When every card on the page was applied, produce the note that lets Task 2
   stop gracefully instead of opening (and applying to) one.

The rule is a pure text predicate (no browser, no network), so it stays
unit-testable. The caller (:mod:`src.tools.linkedin_job_selection`) owns the
browser interaction; this module only decides and records.
"""

from __future__ import annotations

import re

from src.configuration import Settings
from src.state import Task2Outcome


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def card_is_applied(text: str) -> bool:
    """True when a job card's status marks the job as already applied.

    A card that the user has already applied to shows the word **Applied** in its
    status line (e.g. "Applied · 5 months ago"). Only that standalone word
    decides: the age text ("5 months ago", "2 weeks ago") and other statuses
    ("Viewed", "Saved") are ignored, as is an "Easy Apply" badge. Matching is on
    the normalized card text (trim, lowercase, collapse whitespace) because the
    status label's markup and position vary, and an unreadable/empty card is
    never assumed Applied — the caller lets the existing Easy Apply check decide.
    """
    return bool(re.search(r"\bapplied\b", _normalize(text)))


def skip_applied_card(
    label: str,
    *,
    index: int,
    title: str,
    key: str,
    settings: Settings,
    outcome: Task2Outcome,
    applied_seen: set[str],
    notify,
) -> bool:
    """Task 6: skip and record a card that is already marked "Applied".

    Returns ``True`` when the card must be skipped (the caller must not click
    it), ``False`` when it should be considered as a candidate. The skip is only
    applied when ``settings.session.skip_applied`` is set; a card whose status
    cannot be read is never assumed Applied. Each distinct applied card is
    counted/recorded once (keyed by ``key``), so re-reading the list does not
    double-count it.
    """
    if not settings.session.skip_applied or not card_is_applied(label):
        return False
    if key not in applied_seen:
        applied_seen.add(key)
        outcome.applied_jobs_skipped += 1
        outcome.applied_skipped_cards.append({"index": index, "title": title})
        notify(f"Task 2: job {index + 1} is already applied; skipping.")
    return True


def applied_skip_note(outcome: Task2Outcome) -> str | None:
    """Task 6: the note to add when no unapplied job was opened on this page.

    Returns ``None`` when nothing was skipped, so the caller can leave the notes
    untouched. When every card on the page was applied the note says so plainly;
    otherwise it reports how many applied jobs were skipped.
    """
    if outcome.jobs_seen and outcome.applied_jobs_skipped >= outcome.jobs_seen:
        return "no unapplied job found on this page; every job card is already Applied"
    if outcome.applied_jobs_skipped:
        return (
            f"skipped {outcome.applied_jobs_skipped} applied job(s); "
            "no unapplied Easy Apply job was opened"
        )
    return None
