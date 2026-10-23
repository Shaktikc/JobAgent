"""Task 2: open a job's **Easy Apply** button and confirm the details pane.

Split out of :mod:`src.tools.linkedin_job_selection` (which owns the results
list, the card scan, and the Task 2/6/7 flow) so both files stay small enough to
read. This module owns the right-hand **details pane**:

1. Which job the pane currently shows (:func:`read_details_pane_job`), so the
   walk can tell that a card click actually opened the job it clicked.
2. The pane's **apply button** (:func:`find_job_apply_button` /
   :func:`wait_for_job_apply_button`) — "Easy Apply" for Easy Apply jobs,
   "Apply"/"Apply on company website" for external ones.
3. Confirming the Easy Apply form opened (:func:`read_apply_modal` /
   :func:`wait_for_easy_apply_modal`).

Why the pane check matters: clicking a card can leave the pane showing the
*previous* job (a stale/missed card click). An already-applied job's pane has no
Easy Apply control at all, so the walk then wrongly concluded "no Easy Apply for
this job" and skipped a job that **does** offer Easy Apply. The caller therefore
verifies the pane before judging the button (see
:func:`~src.tools.linkedin_job_selection.find_card_by_title`).

The interaction uses browser-use's deterministic CDP actor API (``Page`` /
``Element``); no LLM is involved.
"""

from __future__ import annotations

import asyncio
import re
import time

from src.configuration import Settings
from src.tools.browser import (
    _APPLY_POLL_SECONDS,
    _JOB_CARD_ATTR,
    FIND_APPLY_ROOT_JS,
    _element_label,
    _loads,
    _mark_ai_job_cards,
    _query_elements,
    _safe,
)
from src.tools.linkedin import (
    looks_like_apply_modal,
    looks_like_easy_apply_action,
    looks_like_job_card_label,
)

# The job's apply button in the right-hand details pane. Its label is "Easy Apply"
# for Easy Apply jobs and "Apply"/"Apply on company website" for external ones.
# The AI/semantic results layout renders the button with hashed CSS-in-JS classes
# (no ``jobs-apply-button``), so its accessible label is matched too: ``^="Easy
# Apply to"`` finds "Easy Apply to this job" / "Easy Apply to <job> at <company>",
# and deliberately does not match the results filter pill ("Easy Apply filter.").
_JOB_DETAILS_APPLY_SELECTORS = (
    "div.jobs-search__job-details--container button.jobs-apply-button",
    "div.scaffold-layout__detail button.jobs-apply-button",
    "div.job-view-layout button.jobs-apply-button",
    "div.jobs-details button.jobs-apply-button",
    "button.jobs-apply-button",
    "[data-live-test-job-apply-button]",
    'button[aria-label^="Easy Apply to" i]',
    'a[aria-label^="Easy Apply to" i]',
)

# Controls the broad fallback scan considers when no known selector matches. The
# button selector is kept exactly as LinkedIn's own markup uses it; anchors are
# scanned afterwards because LinkedIn renders the pane's action as a link in some
# states. Job cards and the results filter are excluded by the checks below.
_APPLY_CONTROL_SELECTORS = ("button, [role='button']", "a")

_APPLY_MODAL_QUERY = (
    "() => {\n"
    + FIND_APPLY_ROOT_JS
    + "\n  const root = findApplyRoot();\n"
    + "  return JSON.stringify({\n"
    + "    open: !!root,\n"
    + "    text: root ? (root.innerText || '').slice(0, 1000) : ''\n"
    + "  });\n"
    + "}\n"
)

# Which job the details pane is showing. LinkedIn's page title is
# "<job title> | <company> | LinkedIn" while a job is open, and it follows the
# pane (not the clicked card), which is exactly the signal needed here.
_PANE_JOB_QUERY = (
    "() => {\n"
    + "  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();\n"
    + "  const pane = document.querySelector(\n"
    + "    'div.jobs-search__job-details--container, div.scaffold-layout__detail, '\n"
    + "    + 'div.job-view-layout, div.jobs-details, div.jobs-details__main-content'\n"
    + "  );\n"
    + "  let title = norm(document.title).split('|')[0];\n"
    + "  if (pane) {\n"
    + "    const heading = pane.querySelector('h1, h2');\n"
    + "    if (!title && heading) title = norm(heading.innerText);\n"
    + "  }\n"
    + "  if (/^(jobs?|linkedin)/i.test(title)) title = '';\n"
    + "  return JSON.stringify({ title: norm(title) });\n"
    + "}\n"
)

# How long to wait for a clicked card to show up in the details pane, and how
# often to look. A pane that never switches (a stale card click) must not be
# mistaken for an Easy Apply job. One retry is enough: the retry re-resolves the
# card to a fresh element handle, which is what fixes the stale click.
_PANE_SWITCH_TIMEOUT_SECONDS = 6.0
_PANE_SWITCH_POLL_SECONDS = 0.5


def _title_tokens(text: str) -> list[str]:
    """Comparable word tokens of a job title (case/punctuation-insensitive)."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split()


def pane_shows_job(pane_title: str, card_title: str) -> bool:
    """True when the details pane looks like it is showing ``card_title``.

    Both titles are reduced to word tokens and compared as a *prefix* of one
    another: the pane's title ("Django Developer") is the start of the card's
    label ("Django Developer Adactin Sydney …", or "Django Developer (Verified
    job)"), while a different job's title is not. An unreadable pane title or card
    title counts as a match: the check only ever *adds* a retry, so a layout whose
    title cannot be read keeps working exactly as before.
    """
    pane = _title_tokens(pane_title)
    card = _title_tokens(card_title)
    if not pane or not card:
        return True
    shorter, longer = (pane, card) if len(pane) <= len(card) else (card, pane)
    return longer[: len(shorter)] == shorter


async def read_details_pane_job(page) -> str:
    """The job title the details pane currently shows (``""`` when unreadable)."""
    payload = _loads(await _safe(page.evaluate(_PANE_JOB_QUERY), ""))
    return str(payload.get("title") or "").strip()


async def wait_for_details_pane_job(
    page, card_title: str, timeout_seconds: float = _PANE_SWITCH_TIMEOUT_SECONDS
) -> str:
    """Poll until the details pane shows ``card_title``; return the last title read."""
    deadline = time.monotonic() + timeout_seconds
    pane_title = await read_details_pane_job(page)
    while not pane_shows_job(pane_title, card_title) and time.monotonic() < deadline:
        await asyncio.sleep(min(_PANE_SWITCH_POLL_SECONDS, timeout_seconds))
        pane_title = await read_details_pane_job(page)
    return pane_title


async def _element_is_job_card(element) -> bool:
    """True when ``element`` is a job card, not the details pane's apply button.

    AI/semantic job cards are ``div[role="button"]`` marked with
    ``data-autojob-card`` (see :data:`_JOB_CARD_ATTR`). Their accessible text
    also carries "Easy Apply", so without this check the fallback scan would
    mistake the first card for the apply button and click it instead of the blue
    "Easy Apply" button (the Task 2 bug).

    A real apply button is a ``<button>`` and is never excluded by the label
    heuristic, so a job whose title/company contains a location word (e.g.
    "Remote") is still matched.
    """
    if await _safe(element.get_attribute(_JOB_CARD_ATTR), None) is not None:
        return True
    tag = await _safe(element.evaluate("() => this.tagName"), "") or ""
    if str(tag).upper() in {"BUTTON", "A"}:
        return False
    return looks_like_job_card_label(await _element_label(element))


async def find_job_apply_button(page) -> tuple:
    """Return ``(element, label)`` for the details pane's apply button, or ``(None, "")``.

    A control whose label reads like an Easy Apply *action* is preferred over a
    plain "Apply"/"Apply on company website" button: LinkedIn keeps a stale
    external button in the pane in some states, and taking it would hide the real
    Easy Apply button behind it. When nothing looks like Easy Apply, the first
    known match is still returned (with its label) so the caller can skip the job
    immediately instead of waiting for a button that will never appear.
    """
    # Ensure AI/semantic job cards are marked so the fallback scan below can
    # exclude them: a job card's "Easy Apply" badge is not the apply button.
    await _mark_ai_job_cards(page)
    first_match: tuple = (None, "")
    for selector in _JOB_DETAILS_APPLY_SELECTORS:
        for element in await _query_elements(page, selector):
            label = await _element_label(element)
            if looks_like_easy_apply_action(label):
                return element, label
            if first_match[0] is None:
                first_match = (element, label)
    if first_match[0] is not None:
        return first_match

    # Fall back to scanning interactive controls for an Easy Apply *action*
    # (an Easy Apply label that is not the results filter). Job cards are
    # excluded — their text also contains "Easy Apply" but they are not the
    # blue apply button.
    for selector in _APPLY_CONTROL_SELECTORS:
        for element in await _query_elements(page, selector):
            label = await _element_label(element)
            if not looks_like_easy_apply_action(label):
                continue
            if await _element_is_job_card(element):
                continue
            return element, label
    return None, ""


async def wait_for_job_apply_button(page, settings: Settings) -> tuple:
    """Wait for the details pane's apply button to appear; return ``(element, label)``."""
    deadline = time.monotonic() + settings.session.easy_apply_timeout_seconds
    button, label = await find_job_apply_button(page)
    while button is None and time.monotonic() < deadline:
        await asyncio.sleep(_APPLY_POLL_SECONDS)
        button, label = await find_job_apply_button(page)
    return button, label


async def read_apply_modal(page) -> tuple[bool, str]:
    """Return ``(open, text)`` for the Easy Apply application form/modal."""
    payload = _loads(await _safe(page.evaluate(_APPLY_MODAL_QUERY), ""))
    if not payload.get("open"):
        return False, ""
    text = payload.get("text") or ""
    # An unrelated dialog should not count; require recognisable Easy Apply text
    # when the modal exposes any.
    return (not text or looks_like_apply_modal(text)), text


async def wait_for_easy_apply_modal(page, settings: Settings) -> tuple[bool, str]:
    """Wait for the Easy Apply application form to open; return ``(open, text)``."""
    deadline = time.monotonic() + settings.session.easy_apply_timeout_seconds
    opened, text = await read_apply_modal(page)
    while not opened and time.monotonic() < deadline:
        await asyncio.sleep(_APPLY_POLL_SECONDS)
        opened, text = await read_apply_modal(page)
    return opened, text


__all__ = [
    "find_job_apply_button",
    "pane_shows_job",
    "read_apply_modal",
    "read_details_pane_job",
    "wait_for_details_pane_job",
    "wait_for_easy_apply_modal",
    "wait_for_job_apply_button",
]
