"""Task 9: the on-page status panel's DOM scripts.

The panel renders in the browser's top layer (``popover="manual"``) at the
bottom-left so LinkedIn's modal and the bottom-right Task 5 / Task 3.1 banners
never cover it. Every string is set with ``textContent`` so page/job/LLM text can
never inject markup. Split out of :mod:`src.tools.linkedin_status_overlay` so
each module stays small; the package re-exports the public names.
"""

from __future__ import annotations

# The status panel. It shows only the latest step (the current line is replaced on
# every update). Every string is set via ``textContent``.
_UPDATE_STATUS_JS = r"""
(actor, message) => {
  let box = document.getElementById('autojob-status');
  if (!box) {
    box = document.createElement('div');
    box.id = 'autojob-status';
    box.setAttribute('role', 'status');
    box.setAttribute('aria-live', 'polite');
    box.setAttribute('aria-label', 'AutoJobApply progress');
    box.setAttribute('popover', 'manual');
    box.style.cssText = [
      'position:fixed', 'inset:auto auto 24px 24px', 'margin:0',
      'z-index:2147483647', 'max-width:460px', 'min-width:280px',
      // Feedback only: never intercept a click. The panel is a top-layer popover
      // with the maximum z-index, so without this it can sit over the Easy Apply
      // footer's Next button and swallow the CDP click, leaving the form stuck on
      // the same step (BUG-048).
      'pointer-events:none',
      'background:#ffffff', 'color:#1a1a1a', 'border:2px solid #0a66c2',
      'border-radius:8px', 'box-shadow:0 8px 24px rgba(0,0,0,.35)',
      'padding:14px',
      "font:13px/1.45 -apple-system,'Segoe UI',Roboto,Arial,sans-serif"
    ].join(';');
    const heading = document.createElement('div');
    heading.id = 'autojob-status-heading';
    heading.textContent = 'AutoJobApply is working';
    heading.style.cssText = 'font-weight:600;color:#0a66c2;margin-bottom:6px';
    const current = document.createElement('div');
    current.id = 'autojob-status-current';
    current.style.cssText = 'margin:0';
    box.appendChild(heading);
    box.appendChild(current);
    document.documentElement.appendChild(box);
  }
  if (!box.isConnected) document.documentElement.appendChild(box);
  // Re-raise the panel to the top of the browser's top layer on every update.
  // LinkedIn's Easy Apply modal is itself a top-layer dialog, and its ::backdrop
  // is drawn above any popover opened *before* it (e.g. this panel, created at run
  // start). A plain showPopover() on an already-open popover is a no-op, so the
  // panel would stay behind the modal. Hiding then re-showing moves it to the
  // newest top-layer slot, keeping it in front (like Task 5's answer banner,
  // which is shown later and therefore already on top).
  try {
    if (typeof box.hidePopover === 'function' && box.matches(':popover-open')) {
      box.hidePopover();
    }
  } catch (e) { /* not open, or unsupported */ }
  try {
    if (typeof box.showPopover === 'function') box.showPopover();
  } catch (e) { /* unsupported: fixed + max z-index still applies */ }

  const current = document.getElementById('autojob-status-current');
  if (current) current.textContent = message || '';

  const isLLM = actor === 'llm';
  box.style.borderColor = isLLM ? '#6a3fb5' : '#0a66c2';
  const heading = document.getElementById('autojob-status-heading');
  if (heading) {
    heading.textContent = isLLM
      ? 'AutoJobApply - the LLM is working'
      : 'AutoJobApply is working';
    heading.style.color = isLLM ? '#6a3fb5' : '#0a66c2';
  }
  return true;
}
"""

# Remove the panel once the run ends, so no stale status is left on the page.
_CLEAR_STATUS_JS = r"""
() => {
  const box = document.getElementById('autojob-status');
  if (box) {
    try {
      if (typeof box.hidePopover === 'function') box.hidePopover();
    } catch (e) { /* never shown: nothing to hide */ }
    box.remove();
  }
  return true;
}
"""

# Shown on every LLM line so LLM activity is never mistaken for browser code.
_LLM_PREFIX = "LLM"


def _format_llm(action: str, detail: str = "") -> str:
    """The one-line text for an LLM action/decision (used for the panel + CLI)."""
    action = (action or "").strip()
    detail = (detail or "").strip()
    text = f"{_LLM_PREFIX}: {action}" if action else _LLM_PREFIX
    if detail:
        text = f"{text} - {detail}"
    return text
