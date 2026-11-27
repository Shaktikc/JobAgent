"""Task 32: skip blacklisted companies while scanning LinkedIn results.

The results scanner (:func:`src.tools.linkedin_job_selection._scan_page`) calls
these checks so the skip covers the first job, later jobs, every results page,
and the date-range fallback alike:

1. :func:`skip_blacklisted_card` — before a card is clicked, compare the company
   shown on the card (its own line of card text, or a company element inside the
   card) against the blacklist. A match is never clicked.
2. :func:`skip_blacklisted_pane` — when the card did not show a company, read the
   company from the confirmed job details pane after the card opened, before the
   apply button, description, resume matcher, or **Easy Apply** are touched.

A match is a normal filter: it is recorded on the Task 2 outcome, logged, shown
in the browser status, and the scan moves on. It is not counted as an
application or a scanned job.
"""

from __future__ import annotations

from src.state import Task2Outcome
from src.tools.browser import _safe
from src.tools.company_blacklist import blacklisted_line, get_blacklist, is_blacklisted
from src.tools.linkedin_status_overlay import emit_step

# Company elements inside a results card (classic and newer card layouts).
_CARD_COMPANY_QUERY = """() => {
  const selectors = [
    '.artdeco-entity-lockup__subtitle',
    '.job-card-container__primary-description',
    '.job-card-container__company-name',
    '[class*="company-name"]'
  ];
  for (const selector of selectors) {
    const el = this.querySelector(selector);
    const text = el ? (el.innerText || el.textContent || '').trim() : '';
    if (text) return text;
  }
  return '';
}"""


def _record(outcome: Task2Outcome, index: int, title: str, company: str, notify) -> None:
    """Record one blacklisted posting (once per title/company) and report it."""
    entry = {"index": index, "title": title, "company": company}
    if any(
        seen.get("title") == title and seen.get("company") == company
        for seen in outcome.blacklisted_skipped_cards
    ):
        return
    outcome.blacklisted_jobs_skipped += 1
    outcome.blacklisted_skipped_cards.append(entry)
    shown = title or "(untitled)"
    notify(
        f"Task 32: job {index + 1} ({shown}) is from blacklisted company "
        f"{company!r}; skipping."
    )
    emit_step(notify, f"Skipping {shown} at {company} - company is blacklisted.")


async def card_company(card, label: str) -> str:
    """The blacklisted company named on ``card``, or ``""`` when none is."""
    blacklist = get_blacklist()
    if not blacklist:
        return ""
    line = blacklisted_line(label, blacklist)
    if line:
        return line
    shown = str(await _safe(card.evaluate(_CARD_COMPANY_QUERY), "") or "")
    for candidate in (shown, *shown.splitlines()):
        if is_blacklisted(candidate, blacklist):
            return candidate.strip()
    return ""


async def skip_blacklisted_card(
    card, label: str, *, index: int, title: str, outcome: Task2Outcome, notify
) -> bool:
    """True (and recorded) when ``card`` shows a blacklisted company; never clicks."""
    company = await card_company(card, label)
    if not company:
        return False
    _record(outcome, index, title, company, notify)
    return True


async def skip_blacklisted_pane(
    page, *, index: int, title: str, outcome: Task2Outcome, notify
) -> bool:
    """True (and recorded) when the open details pane's company is blacklisted."""
    blacklist = get_blacklist()
    if not blacklist:
        return False
    # Lazy: the reader package imports the browser helpers at load time.
    from src.tools.linkedin_best_matching_resume.description_reader import (
        read_job_description,
    )

    description = await read_job_description(page)
    if not is_blacklisted(description.company, blacklist):
        return False
    _record(outcome, index, title, description.company.strip(), notify)
    return True


def blacklist_skip_note(outcome: Task2Outcome) -> str | None:
    """The stop note when blacklisted postings were skipped and no job was chosen."""
    if not outcome.blacklisted_jobs_skipped:
        return None
    return f"skipped {outcome.blacklisted_jobs_skipped} job(s) from blacklisted companies"


__all__ = [
    "blacklist_skip_note",
    "card_company",
    "skip_blacklisted_card",
    "skip_blacklisted_pane",
]
