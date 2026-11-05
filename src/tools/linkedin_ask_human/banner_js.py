"""Task 5: the browser banner's DOM scripts (show, poll, hide, confirm).

Split out of :mod:`src.tools.linkedin_ask_human` so each module stays small.
The banner has no input: it tells the human the agent does not know a question
and asks them to answer it in the real form control. The question text is set
via ``textContent`` so page content can never inject markup.
"""

from __future__ import annotations

# Task 5: a visible banner that tells the human the agent cannot answer a
# question and asks them to type the answer into the form field itself. The
# question text is set via ``textContent`` so page content can never inject
# markup. The banner records its state in ``data-autojob-state`` (``pending`` /
# ``saved`` / ``skipped``) so the agent can poll it without blocking the page, and
# shows a "saved" confirmation once the answer is stored. There is no input in the
# banner: the answer is read from the form control the human edits.
_SHOW_UNKNOWN_JS = r"""
(question, hint) => {
  let box = document.getElementById('autojob-unknown');
  if (!box) {
    box = document.createElement('div');
    box.id = 'autojob-unknown';
    box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-label', 'JobAgent needs an answer');
    // Render in the browser's top layer so LinkedIn's modal (its own high z-index
    // and stacking context) can never cover the banner. The ``popover`` top layer,
    // unlike a modal ``<dialog>``, leaves the rest of the page interactive.
    box.setAttribute('popover', 'manual');
    box.style.cssText = [
      'position:fixed', 'inset:auto 24px 24px auto', 'margin:0',
      'z-index:2147483647', 'max-width:420px', 'background:#ffffff',
      'color:#1a1a1a', 'border:2px solid #b24020', 'border-radius:8px',
      'box-shadow:0 8px 24px rgba(0,0,0,.35)', 'padding:16px',
      "font:14px/1.4 -apple-system,'Segoe UI',Roboto,Arial,sans-serif"
    ].join(';');
    const heading = document.createElement('div');
    heading.textContent = 'JobAgent does not know this answer';
    heading.style.cssText = 'font-weight:600;color:#b24020;margin-bottom:8px';
    const q = document.createElement('div');
    q.id = 'autojob-unknown-question';
    q.style.cssText = 'margin-bottom:8px';
    const hintEl = document.createElement('div');
    hintEl.id = 'autojob-unknown-hint';
    hintEl.style.cssText = 'margin-bottom:8px;color:#555;font-size:13px';
    const instruction = document.createElement('div');
    instruction.id = 'autojob-unknown-instruction';
    instruction.textContent =
      'Answer it in the form on the page (type or choose an option). '
      + 'Finish with blur, Enter, or Done. For multiple choices, click Done.';
    instruction.style.cssText = 'margin-bottom:8px;color:#555;font-size:13px';
    const status = document.createElement('div');
    status.id = 'autojob-unknown-status';
    status.setAttribute('role', 'status');
    status.style.cssText =
      'margin-bottom:8px;color:#0a7b34;font-weight:600;display:none';
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:8px;justify-content:flex-end';
    const skip = document.createElement('button');
    skip.id = 'autojob-unknown-skip';
    skip.type = 'button';
    skip.textContent = 'Skip';
    skip.style.cssText = 'padding:6px 12px;border:1px solid #666;border-radius:4px;cursor:pointer';
    const done = document.createElement('button');
    done.id = 'autojob-unknown-done';
    done.type = 'button';
    done.textContent = 'Done';
    done.disabled = true;
    done.style.cssText = skip.style.cssText;
    done.addEventListener('click', () => {
      const state = window.__autojobFormAnswer;
      if (state) { state.done = true; state.confirmed = true; state.activity = Date.now(); }
    });
    row.appendChild(done);
    row.appendChild(skip);
    box.appendChild(heading);
    box.appendChild(q);
    box.appendChild(hintEl);
    box.appendChild(instruction);
    box.appendChild(status);
    box.appendChild(row);
    skip.addEventListener('click', () => box.setAttribute('data-autojob-state', 'skipped'));
  }
  // A popover outside a native modal is painted but remains inert. Physical
  // clicks then hit the dialog backdrop and trigger LinkedIn's discard prompt.
  // Keep the banner in the modal's DOM subtree as well as the top layer.
  const dialogs = Array.from(document.querySelectorAll('dialog[open]'));
  const parent = dialogs.reverse().find(dialog => dialog.matches(':modal'))
    || document.documentElement;
  if (box.parentElement !== parent) parent.appendChild(box);
  try {
    if (typeof box.showPopover === 'function') box.showPopover();
  } catch (e) { /* already open, or unsupported: fixed + max z-index still applies */ }
  box.setAttribute('data-autojob-state', 'pending');
  document.getElementById('autojob-unknown-done').disabled = true;
  const q = document.getElementById('autojob-unknown-question');
  if (q) q.textContent = question || 'this question';
  const hintEl = document.getElementById('autojob-unknown-hint');
  if (hintEl) {
    hintEl.textContent = hint || '';
    hintEl.style.display = hint ? 'block' : 'none';
  }
  const statusEl = document.getElementById('autojob-unknown-status');
  if (statusEl) {
    statusEl.textContent = '';
    statusEl.style.display = 'none';
  }
  return true;
}
"""

# Read the banner's current state (``pending`` / ``skipped``).
_READ_UNKNOWN_JS = r"""
() => {
  const box = document.getElementById('autojob-unknown');
  if (!box) return JSON.stringify({ present: false });
  return JSON.stringify({
    present: true,
    state: box.getAttribute('data-autojob-state') || 'pending'
  });
}
"""

# Remove the banner and reset the watcher once the question is resolved.
_HIDE_UNKNOWN_JS = r"""
() => {
  const box = document.getElementById('autojob-unknown');
  if (box) box.remove();
  const state = window.__autojobFormAnswer;
  if (state) {
    state.value = '';
    state.done = false;
    state.confirmed = false;
  }
  return true;
}
"""

# Show a "saved" confirmation in the banner so the human knows the answer was
# stored (Task 5). ``textContent`` keeps the answer from injecting markup.
_MARK_SAVED_JS = r"""
(answer) => {
  const box = document.getElementById('autojob-unknown');
  if (!box) return false;
  try {
    if (typeof box.showPopover === 'function') box.showPopover();
  } catch (e) { /* already open, or unsupported */ }
  const status = document.getElementById('autojob-unknown-status');
  if (status) {
    status.textContent = '\u2713 Saved: ' + (answer || '');
    status.style.display = 'block';
  }
  box.setAttribute('data-autojob-state', 'saved');
  return true;
}
"""

# How long the "saved" confirmation stays visible before the banner closes.
_SAVED_VISIBLE_SECONDS = 1.5

# Dump the group containers of a question whose label could not be read (or a
# radio group), so the real markup can be inspected (written under ``data/debug``
# by the caller).
_DUMP_HOSTS_JS = r"""
(markers, name) => {
  const list = (markers || []).map(String).filter(Boolean);
  const groupName = name ? String(name) : '';
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s;
  const parts = [];
  const add = (el) => {
    if (!el) return;
    const box = el.closest(
      '.fb-dash-form-element, .fb-form-element, .fb-form-element-wrapper, '
      + '.jobs-easy-apply-form-element, .jobs-easy-apply-form-section__grouping, '
      + '.jobs-easy-apply-form-section'
    ) || el.parentElement;
    if (box && parts.indexOf(box.outerHTML) === -1) parts.push(box.outerHTML);
  };
  for (const m of list) {
    add(document.querySelector('[data-autojob-fill="' + esc(m) + '"]'));
  }
  if (groupName) {
    document.querySelectorAll(
      'input[name="' + esc(groupName) + '"], [role="radio"][name="' + esc(groupName) + '"]'
    ).forEach(add);
  }
  return JSON.stringify({ html: parts.join('\n\n') });
}
"""
