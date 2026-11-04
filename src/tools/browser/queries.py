"""Shared DOM queries, copied intact from the browser entry point."""

# Attribute used to mark AI/semantic job cards (div[role="button"]) so the
# classic selectors and CDP element resolution can find them. Also used by
# :mod:`src.tools.linkedin_job_selection` (Task 2).
_JOB_CARD_ATTR = "data-autojob-card"

# How long to keep waiting for the results list to render after a search.
_RESULTS_WAIT_SECONDS = 20.0
# Poll interval used while waiting for the details pane / apply modal.
_APPLY_POLL_SECONDS = 0.5

_RESULTS_QUERY = """
() => JSON.stringify({
  count: document.querySelectorAll(
    'li.jobs-search-results__list-item, li.scaffold-layout__list-item, '
    + 'div.job-card-container, div.jobs-search-results-list__list-item, '
    + 'ul.jobs-search__results-list > li'
  ).length
})
"""

# LinkedIn's AI/semantic results page (origin=SEMANTIC_SEARCH_LANDING_PAGE)
# renders its job cards as div[role="button"], not the classic <li> items the
# classic selectors above match. Scan those controls and mark the ones that look
# like job cards with `data-autojob-card` (see _JOB_CARD_ATTR), so results_count
# and read_job_cards can find them and the run never stalls waiting for cards
# that the classic selectors cannot see.
_AI_JOB_CARDS_JS = r"""
() => {
  // Clear any stale markers from a previous scan.
  document.querySelectorAll('[data-autojob-card]').forEach(
    (el) => el.removeAttribute('data-autojob-card')
  );
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  let n = 0;
  document.querySelectorAll('div[role="button"]').forEach((el) => {
    const t = norm(el.innerText);
    if (!t || t.length < 40) return;              // a card has a title + metadata
    if (/^easy apply/i.test(t)) return;           // not the apply button / filter
    if (!/(on-site|hybrid|remote|posted|actively reviewing|applied|promoted)/i.test(t)) return;
    el.setAttribute('data-autojob-card', 'job' + n);
    n += 1;
  });
  return JSON.stringify({ count: n });
}
"""


# Locate the open Easy Apply surface (shared by Tasks 2 and 4). LinkedIn renders
# it in one of two ways:
#   * the classic artdeco dialog (``.jobs-easy-apply-modal`` / ``.artdeco-modal``),
#   * or, on the AI/semantic job view, an **inline** full-page form whose classes
#     are hashed (no artdeco classes), identified by the "Apply to <company>"
#     heading and its application controls.
# This snippet is injected into a query and defines ``findApplyRoot()``, which
# returns the container element for either form (or ``null`` when none is open).
FIND_APPLY_ROOT_JS = r"""
  const findApplyRoot = () => {
    const isVisible = (el) => !!el && el.getClientRects().length > 0;
    const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
    // 1) The classic Easy Apply dialog. A page can also carry unrelated, hidden
    //    dialogs (e.g. "Save this job") earlier in the DOM, so never trust the
    //    first match: prefer the Easy Apply dialog, then the first *visible*
    //    dialog holding form controls or Easy Apply text.
    const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4'))
      .filter(isVisible);
    const applyHeading = headings.find((h) => /^apply to\b/i.test(norm(h.innerText))) || null;

    // 0) LinkedIn's newer SDUI Easy Apply renders a native ``<dialog>`` (no
    //    artdeco classes, no role="dialog") that contains the "Apply to <company>"
    //    heading. Return that dialog directly: its heading renders a moment before
    //    the controls, and the generic ancestor climb below would otherwise return
    //    the heading itself (zero fields) or a page-level ancestor carrying an
    //    unrelated "Next" button — both made the walk stop at a half-rendered form
    //    (BUG-056). ``closest`` keeps us on the real modal in either render order.
    const applyDialog = applyHeading
      ? applyHeading.closest('dialog, [role="dialog"]')
      : null;
    if (applyDialog && isVisible(applyDialog)) return applyDialog;

    const candidates = Array.from(document.querySelectorAll(
      'div.jobs-easy-apply-modal, div[role="dialog"].artdeco-modal, '
      + '.artdeco-modal--layer-default, div[data-test-modal-container], .artdeco-modal, '
      + 'dialog[open]'
    ));
    const easy = candidates.find((el) => el.classList.contains('jobs-easy-apply-modal'));
    if (easy && isVisible(easy)) return easy;
    const visible = candidates.filter(isVisible);
    const applyish = visible.find((el) =>
      /easy apply|application|apply to\b/i.test(el.innerText || '')
    );
    const formish = visible.find((el) => el.querySelector(
      'input:not([type=hidden]), textarea, select, [role="radio"], [role="checkbox"]'
    ));
    // Never fall back to a hidden Easy Apply dialog: a closed modal left in the
    // DOM with ``display:none`` is not an open application form (Task 16 needs the
    // close check to see the difference).
    const dialog = applyish || formish || visible[0] || null;
    if (dialog) return dialog;

    // 2) The inline full-page form. Anchor on an application control (a phone
    //    field or a select holding an email), then climb to the closest ancestor
    //    that also holds a navigation/submit button. Stop before the page body so
    //    an unrelated page-level "Next" can never be mistaken for the form.
    const anchor = Array.from(document.querySelectorAll('input[type="tel"], select'))
      .filter(isVisible)
      .find((el) => (el.getAttribute('type') || '').toLowerCase() === 'tel'
        || /@/.test(el.value || ''));
    const heading = applyHeading;
    if (!anchor && !heading) return null;
    let el = anchor || heading;
    for (let i = 0; i < 16 && el; i++) {
      const tag = (el.tagName || '').toUpperCase();
      if (tag === 'BODY' || tag === 'HTML') break;
      const hasNav = Array.from(el.querySelectorAll('button, [role="button"]')).some((b) =>
        /next|continue|submit application|review/i.test(
          norm(b.innerText) + ' ' + (b.getAttribute('aria-label') || '')
        )
      );
      if (hasNav && (!anchor || el.contains(anchor))
          && (!heading || el.contains(heading))) return el;
      el = el.parentElement;
    }
    // Never return the heading itself: it contains no fields or buttons.
    return heading ? heading.parentElement : null;
  };
"""
