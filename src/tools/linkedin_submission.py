"""Task 8: detect the human's post-apply submission on LinkedIn.

Split out of :mod:`src.tools.linkedin_apply_loop` so each module stays small.

LinkedIn's SDUI results page does not render the post-apply confirmation as an
artdeco dialog: it can be a bare native ``<dialog>`` (or an overlay without a
role), and the details pane then keeps a plain **"Application submitted"** status.
The open job's card also flips to **Applied**. These helpers read those signals
and decide whether the human's submission was confirmed.

The card fallback matches the job's **title and company**: matching the title
alone selected a different, longer-titled job that was already Applied before the
wait, which made the real submission look stale and left the run waiting
(BUG-060).
"""

from __future__ import annotations

import json
import re

from src.tools.browser import FIND_APPLY_ROOT_JS, _loads, _safe

# Phrases that confirm the human's application was sent. LinkedIn's confirmation
# copy varies, so match any of these in a visible dialog/heading.
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
# LinkedIn's newer post-apply dialog. Keep in sync with the regex in
# ``_SUBMISSION_QUERY_TEMPLATE``.
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
    status_submitted: bool = False,
    status_was_submitted: bool = False,
) -> bool:
    """Decide whether the human's submission is confirmed.

    Strong signals, in order:

    * the confirmation dialog/heading is visible;
    * the details pane now reads **"Application submitted"** (a *new* signal, not
      one already on screen before the wait);
    * the Easy Apply form is closed **and** the open job's card now reads
      **"Applied"** — a card only flips to Applied after a real submit, so an
      X-dismissed form does not trigger it.

    ``card_was_applied`` / ``status_was_submitted`` guard the stale cases: a card
    or status that already read Applied before the wait is not evidence of a
    submission now.
    """
    if looks_like_submission(confirmation):
        return True
    if status_submitted and not status_was_submitted and not form_open:
        return True
    if card_was_applied:
        return False
    return card_applied and not form_open


# Probe the page for a submission confirmation. ``__JOB_TITLE__``/``__COMPANY__``
# are replaced with JSON string literals so the card fallback matches the open
# job's own card rather than any job whose title merely contains the wanted text.
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
  // A heading/paragraph confirmation, without the bare details-pane status: the
  // status phrase is tracked as its own "new since the wait started" signal.
  const headingRe = new RegExp(
    "application (?:was )?sent|application received|"
    + "you(?:'ve| have) applied|successfully applied|you applied", "i"
  );
  // ``findApplyRoot`` can mistake the post-apply confirmation for the open form
  // (its text contains "application"), which blocked the card fallback; a dialog
  // carrying a confirmation is never an open Easy Apply form (BUG-060).
  const formOpen = !!form && !confirmRe.test(norm(form.innerText));

  let confirmation = '';
  let doneMarker = '';
  let i = 0;
  // Keep in sync with _DISMISS_HINTS in this module. Never add "Update profile":
  // the post-apply promo offers that alongside "Not now", and clicking it would
  // edit the human's profile.
  const dismissRe = /^(done|dismiss|close|got it|not now|no thanks|maybe later|skip)$/i;
  const preferRe = /^(not now|no thanks|maybe later|skip)$/i;
  // LinkedIn's SDUI dialog can be a bare <dialog> or an overlay without a role,
  // so the classic artdeco hooks alone missed the confirmation (BUG-060).
  const dialogs = Array.from(document.querySelectorAll(
    'dialog, div[role="dialog"], [role="alertdialog"], [aria-modal="true"], '
    + '.artdeco-modal, div[data-test-modal-container], '
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
  if (!confirmation) {
    // A native <dialog> without a dismiss label still confirms the submission;
    // read a short visible heading/paragraph that carries the confirmation.
    const node = Array.from(document.querySelectorAll('h1, h2, h3, p'))
      .filter(visible)
      .find((el) => {
        const text = norm(el.innerText);
        return headingRe.test(text) && text.length < 300;
      });
    if (node) confirmation = norm(node.innerText).slice(0, 500);
  }

  // The details pane states the open job's status in plain text; it is the most
  // reliable post-submit signal once the dialog has been dismissed.
  const statusSubmitted = Array.from(document.querySelectorAll('h2, h3, p, span, div'))
    .filter(visible)
    .some((el) => /^application submitted$/i.test(norm(el.innerText)));

  // Fallback: the open job's own results card now reads "Applied". Match the
  // card's *title line* exactly (LinkedIn repeats the title, sometimes with
  // "(Verified job)"): a plain substring match picked a different "Senior
  // Software Engineer" card that was already Applied (BUG-060). The company, when
  // known, can still disambiguate same-titled jobs.
  const wanted = norm(__JOB_TITLE__).toLowerCase();
  const company = norm(__COMPANY__).toLowerCase();
  const headOf = (card) => {
    const lines = (card.innerText || '').split('\n')
      .map((line) => line.trim()).filter(Boolean);
    return (lines[0] || '').replace(/\s*\(verified job\)\s*$/i, '').toLowerCase();
  };
  let cardApplied = false;
  if (wanted) {
    const cards = Array.from(document.querySelectorAll(
      'li.jobs-search-results__list-item, li.scaffold-layout__list-item, '
      + 'div.job-card-container, div.jobs-search-results-list__list-item, '
      + 'ul.jobs-search__results-list > li, [data-autojob-card]'
    ));
    const card = cards.find((c) => {
      if (headOf(c) === wanted) return true;
      if (!company) return false;
      const text = norm(c.innerText).toLowerCase();
      return text.includes(wanted) && text.includes(company);
    });
    if (card) cardApplied = /(^|\s)applied(\s|·|$)/i.test(norm(card.innerText));
  }

  return JSON.stringify({
    form_open: formOpen,
    confirmation: confirmation,
    card_applied: cardApplied,
    status_submitted: statusSubmitted,
    done_marker: doneMarker
  });
}
"""
)


def _submission_query(title: str, company: str = "") -> str:
    """Build the submission probe with the open job's title/company embedded safely."""
    return _SUBMISSION_QUERY_TEMPLATE.replace(
        "__JOB_TITLE__", json.dumps(title or "")
    ).replace("__COMPANY__", json.dumps(company or ""))


async def read_submission_state(page, title: str = "", company: str = "") -> dict:
    """Return the page's submission signals for the open job (see the probe)."""
    payload = _loads(await _safe(page.evaluate(_submission_query(title, company)), ""))
    return {
        "form_open": bool(payload.get("form_open")),
        "confirmation": str(payload.get("confirmation") or ""),
        "card_applied": bool(payload.get("card_applied")),
        "status_submitted": bool(payload.get("status_submitted")),
        "done_marker": str(payload.get("done_marker") or ""),
    }


__all__ = [
    "is_dismiss_label",
    "looks_like_submission",
    "read_submission_state",
    "submission_detected",
]
