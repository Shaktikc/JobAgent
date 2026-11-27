"""Close LinkedIn's "Job search safety reminder" dialog and skip the job.

For some postings, clicking **Easy Apply** does not open the application form but
a "Job search safety reminder" dialog ("Research the company" / "Report
suspicious jobs") with **Review job post** and **Continue applying** buttons.
The user's rule for these jobs is: close the dialog and move to the next
application. Only the dialog's own dismiss (X) control is clicked — never
**Continue applying** — with Escape as a fallback.
"""

from __future__ import annotations

import asyncio

from src.tools.browser import _loads, _safe

# Text that identifies the reminder. The heading is the primary signal; the two
# buttons together are a fallback in case the heading wording changes.
_SAFETY_REMINDER_JS = r"""
(action) => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const visible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
  };
  const candidates = Array.from(document.querySelectorAll(
    "[role='dialog'], [role='alertdialog'], dialog[open], .artdeco-modal"
  ));
  const isReminder = (el) => {
    const text = clean(el.innerText);
    if (text.includes('job search safety reminder')) return true;
    return text.includes('continue applying') && text.includes('review job post');
  };
  const dialog = candidates.find((el) => visible(el) && isReminder(el));
  if (!dialog) return JSON.stringify({found: false, clicked: false});
  if (action !== 'close') return JSON.stringify({found: true, clicked: false});
  const buttons = Array.from(dialog.querySelectorAll('button'));
  const label = (b) => clean(b.getAttribute('aria-label') || b.innerText);
  const dismiss = buttons.find((b) => visible(b) && (
    b.classList.contains('artdeco-modal__dismiss') ||
    b.hasAttribute('data-test-modal-close-btn') ||
    /^(dismiss|close)\b/.test(label(b))
  ));
  if (!dismiss) return JSON.stringify({found: true, clicked: false});
  dismiss.click();
  return JSON.stringify({found: true, clicked: true});
}
""".strip()

_CLOSE_ATTEMPTS = 3
_CLOSE_POLL_SECONDS = 0.5


async def safety_reminder_open(page) -> bool:
    """True when the "Job search safety reminder" dialog is showing."""
    if page is None:
        return False
    payload = _loads(await _safe(page.evaluate(_SAFETY_REMINDER_JS, "read"), ""))
    return bool(payload.get("found"))


async def close_safety_reminder(page) -> bool:
    """Close the reminder via its X (Escape as a fallback); True once it is gone."""
    if page is None:
        return False
    for _ in range(_CLOSE_ATTEMPTS):
        payload = _loads(await _safe(page.evaluate(_SAFETY_REMINDER_JS, "close"), ""))
        if not payload.get("found"):
            return True
        if not payload.get("clicked"):
            await _safe(page.press("Escape"))
        await asyncio.sleep(_CLOSE_POLL_SECONDS)
        if not await safety_reminder_open(page):
            return True
    return not await safety_reminder_open(page)


__all__ = ["close_safety_reminder", "safety_reminder_open"]
