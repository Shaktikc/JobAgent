"""Task 9: show live progress in the browser on the LinkedIn page.

The agent drives one browser page for the whole run (Tasks 1-8). This module
renders a small, always-updating **status panel** on that same page so the human
can see, in plain language, what the code is doing at each moment — and, whenever
the LLM is invoked, exactly what the LLM is doing and what it decided.

Design goals:

* **Same page, same session.** The panel is injected into the run's live page
  (``get_run(run_id).page``), never a separate window or tab.
* **Coexists with the ask-the-human banners.** Task 5
  (:mod:`src.tools.linkedin_ask_human`) and Task 3.1
  (:mod:`src.tools.linkedin_best_matching_resume`) already render top-layer
  ``popover`` banners in the bottom-right; this panel lives in the bottom-left so
  all three can be visible at once.
* **Stays in front of LinkedIn's modal.** The Easy Apply modal is itself a
  top-layer dialog; its backdrop is drawn above any popover opened *before* it.
  The panel re-raises itself to the newest top-layer slot on every update
  (hide + re-show), so it remains visible and readable in front of the modal.
* **Best-effort and non-blocking.** A missing/failed page never raises or delays a
  step: the panel is feedback only and automation never depends on it.
* **Untrusted text.** Every string is set with ``textContent`` (never
  ``innerHTML``), so page/job/LLM text can never inject markup.

:class:`StatusReporter` is created in :func:`src.tools.browser.start_tasks` (as
soon as the page exists) and stored on the run, so later modules reach it via
``get_reporter(run_id)``. It wraps the existing CLI ``notify`` callback: calling
the reporter still prints to the CLI exactly as before, while :meth:`step` and
:meth:`llm` additionally update the on-page panel. The module-level
:func:`emit_step` / :func:`emit_llm` helpers work whether the status object is a
full reporter or a plain ``notify`` callable, so existing test fakes keep working.
"""

from __future__ import annotations

import asyncio

# The status panel. It renders in the browser's top layer (``popover="manual"``)
# at the bottom-left so LinkedIn's modal and the bottom-right Task 5 / Task 3.1
# banners never cover it. It shows only the latest step (the current line is
# replaced on every update). Every string is set via ``textContent``.
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


class StatusReporter:
    """Pushes agent/LLM status to the CLI and the on-page panel (Task 9).

    The reporter is **callable**, so it can stand in anywhere the old
    ``progress``/``notify`` callback was passed; calling it prints to the CLI only
    (technical detail), while :meth:`step` and :meth:`llm` also update the panel
    with plain-language, human-facing text.
    """

    def __init__(self, emit=None, page=None) -> None:
        self.emit = emit or (lambda _message: None)
        self._page = page

    def bind_page(self, page) -> None:
        """Attach the live page the panel should render into."""
        self._page = page

    def __call__(self, message: str) -> None:
        """Technical notify line: CLI only (matches the old ``notify`` callback)."""
        self.emit(message)

    def step(self, message: str) -> None:
        """Plain-language agent step: printed and shown on the page."""
        self.emit(message)
        self._update("agent", message)

    def llm(self, action: str, detail: str = "") -> None:
        """An LLM action/decision: printed and shown on the page, marked as LLM."""
        text = _format_llm(action, detail)
        self.emit(text)
        self._update("llm", text)

    def _update(self, actor: str, message: str) -> None:
        page = self._page
        if page is None or not message:
            return
        self._schedule(page, _UPDATE_STATUS_JS, actor, message)

    def _schedule(self, page, js: str, *args) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no event loop: CLI-only, never block the caller
        loop.create_task(self._evaluate(page, js, *args))

    async def _evaluate(self, page, js: str, *args) -> None:
        try:
            await page.evaluate(js, *args)
        except Exception:  # noqa: BLE001 - the panel is best-effort feedback
            pass

    async def clear(self) -> None:
        """Remove the panel from the page (called once the run ends)."""
        page, self._page = self._page, None
        if page is None:
            return
        try:
            await page.evaluate(_CLEAR_STATUS_JS)
        except Exception:  # noqa: BLE001 - nothing to clean up if the page is gone
            pass


def emit_step(status, message: str) -> None:
    """Emit an agent step through a reporter, or a plain ``notify`` callable."""
    if status is None or not message:
        return
    step = getattr(status, "step", None)
    if callable(step):
        step(message)
    elif callable(status):
        status(message)


def emit_llm(status, action: str, detail: str = "") -> None:
    """Emit an LLM action through a reporter, or a plain ``notify`` callable."""
    if status is None:
        return
    llm = getattr(status, "llm", None)
    if callable(llm):
        llm(action, detail)
    elif callable(status):
        status(_format_llm(action, detail))


__all__ = [
    "StatusReporter",
    "emit_llm",
    "emit_step",
]
