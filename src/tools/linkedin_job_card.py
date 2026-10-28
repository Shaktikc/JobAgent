"""Task 2: resolve a results card and open its details pane.

Extracted from :mod:`src.tools.linkedin_job_selection` so that module stays under
the project's file-size limit. The public names are re-exported by
``linkedin_job_selection``, so existing imports keep working unchanged.

The details pane is checked after every card click: a click can leave the pane on
the *previous* job (an already-applied job's pane has no Easy Apply control at
all), which used to be reported as "no Easy Apply" and skipped a job that does
offer it (BUG-036).
"""

from __future__ import annotations

import asyncio
import re

from src.configuration import Settings
from src.tools.browser import _element_label, _pace, _safe
from src.tools.linkedin_job_apply_button import (
    pane_shows_job,
    read_details_pane_job,
    wait_for_details_pane_job,
)


def _first_line(text: str) -> str:
    """First non-empty line of ``text`` (a job card's title), truncated."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:200]
    return ""


# Status badges LinkedIn appends to a card's title line after it is opened (live:
# "Senior Engineer (Verified job)"). They identify the same posting, so they must
# not make a skipped job look new (Task 16's skip set) or defeat a card retry.
_TITLE_STATUS_SUFFIX = re.compile(r"\s*\(\s*verified job\s*\)\s*$", re.IGNORECASE)


def _job_key(title: str, index: int) -> str:
    """Stable identity for a results-list job (its title, or index when blank)."""
    normalized = re.sub(r"\s+", " ", (title or "").strip().lower())
    normalized = _TITLE_STATUS_SUFFIX.sub("", normalized).strip()
    return normalized or f"#{index}"


async def find_card_by_title(page, title: str):
    """Re-resolve the job card whose title matches ``title`` (fresh element handle).

    Used by :func:`open_job_card` to retry a click that did not open the job: the
    results list re-renders when a card is clicked, so a handle read before the
    click can go stale (the Task 2 bug behind BUG-019 and BUG-036). The match
    tolerates small label changes (a re-rendered "Posted 2 days ago" badge), so it
    compares the titles as well as their normalized form.
    """
    # Imported lazily: linkedin_job_selection imports this module at load time.
    from src.tools.linkedin_job_selection import read_job_cards

    wanted = _job_key(title, 0)
    for index, card in enumerate(await read_job_cards(page)):
        first = _first_line(await _element_label(card))
        if not first:
            continue
        if _job_key(first, index) == wanted:
            return card
        if title.strip() and pane_shows_job(first, title):
            return card
    return None


async def open_job_card(page, card, title: str, settings: Settings, notify) -> tuple[bool, str]:
    """Click ``card`` until the details pane shows ``title``; return ``(opened, pane_title)``.

    The pane is checked because a click can leave it showing the *previous* job —
    an already-applied job's pane has no Easy Apply control at all, which would
    otherwise be misread as "no Easy Apply" and skip a job that offers it. A
    mismatch re-clicks the card through a freshly resolved handle (once); if the
    pane still does not match, the caller reports that instead of guessing.
    """
    pane_title = await read_details_pane_job(page)
    for attempt in range(2):
        element = card
        if attempt:
            element = await find_card_by_title(page, title)
            if element is None:
                return False, pane_title
            notify(f"Task 2: the details pane did not open {title!r}; clicking it again.")
        await _safe(element.evaluate("() => this.scrollIntoView({block: 'center'})"))
        try:
            await element.click()
        except Exception as exc:  # noqa: BLE001 - try the next job
            return False, f"click failed: {exc}"
        if settings.session.post_click_wait_seconds:
            await asyncio.sleep(settings.session.post_click_wait_seconds)
        await _pace(settings)
        pane_title = await wait_for_details_pane_job(
            page, title, settings.session.pane_switch_timeout_seconds
        )
        if pane_shows_job(pane_title, title):
            return True, pane_title
    return False, pane_title


__all__ = [
    "_first_line",
    "_job_key",
    "find_card_by_title",
    "open_job_card",
]
