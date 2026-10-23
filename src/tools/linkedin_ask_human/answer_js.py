"""Task 5: watch the form for the human's answer and read it back.

Split out of :mod:`src.tools.linkedin_ask_human` so each module stays small.
The banner has no input, so the human edits the actual form control; the watcher
records the edited value on the page and the reader combines it with the live
control value. Both are re-scoped for each question, so an unrelated edit is
never mistaken for the answer.

A ``<select>``'s prompt option ("Select an option") is never an answer — see
:data:`_SELECT_PROMPT_JS` (BUG-037).
"""

from __future__ import annotations

# Task 5: watch the form for the human's answer. The banner has no input, so the
# human edits the actual form control; this records the edited value on the page
# and flags when the edit is finished. A single document-level listener is
# installed once and re-scoped for each question, so the agent can poll the value
# without blocking.
#
# The form is dynamic (see AGENTS.md): LinkedIn renders many screening questions
# as ``<div role="radio" aria-checked="...">`` rather than real ``<input>``s.
# Clicking one of those fires only ``click`` (no ``input``/``change``), so a click
# is recorded too — after a tick, once the page has set ``aria-checked``. Each
# recorded control is checked against the marker(s) of the question being asked
# (``markers``), so editing an unrelated field is never mistaken for the answer.
_WATCH_FORM_ANSWER_JS = r"""
(markers) => {
  const KEY = '__autojobFormAnswer';
  const allowed = (markers || []).map(String);
  const previous = window[KEY];
  if (previous && previous.installed) {
    previous.value = '';
    previous.done = false;
    previous.scope = allowed;
    return true;
  }
  const state = { installed: true, value: '', done: false, scope: allowed };
  window[KEY] = state;

  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s;

  // A <select>'s prompt option ("Select an option") is not an answer. LinkedIn
  // renders it with value="" and disabled; other forms give it a non-empty value
  // but prompt text. Clicking a select to open its dropdown, or clicking away
  // without choosing, must never be recorded as the human's answer (BUG-037).
  const isSelectPrompt = (el) => {
    const opt = el && el.options ? el.options[el.selectedIndex] : null;
    if (!opt) return true;
    const value = norm(el.value || '');
    const text = norm(opt.text || opt.value);
    if (/^(?:please\s+)?(?:select|choose|pick)\b/i.test(text)) return true;
    if (opt.disabled && !value) return true;
    return !text && !value;
  };

  const inScope = (node, el) => {
    if (!state.scope.length) return true;  // no scope: accept any control
    const holders = [node, el].filter(Boolean).map(
      (n) => n.closest && n.closest('[data-autojob-fill]')
    ).filter(Boolean);
    return holders.some(
      (h) => state.scope.indexOf(h.getAttribute('data-autojob-fill')) !== -1
    );
  };

  const resolveControl = (node) => {
    if (!node || !node.closest) return null;
    const label = node.closest('label');
    if (label) {
      if (label.control) return label.control;
      if (label.htmlFor) {
        const forEl = document.getElementById(label.htmlFor);
        if (forEl) return forEl;
      }
    }
    return node.closest('input, textarea, select, [role="radio"], [role="checkbox"]');
  };

  const optionText = (el) => {
    // A choice's visible option text comes first: LinkedIn sets a role=radio
    // container's aria-label to the *question*, not the option.
    if (norm(el.innerText)) return norm(el.innerText);
    const nested = el.querySelector ? el.querySelector('input') : null;
    const own = (el.labels && el.labels[0])
      || (nested && nested.labels && nested.labels[0]) || null;
    if (own && norm(own.innerText)) return norm(own.innerText);
    if (el.id) {
      const l = document.querySelector('label[for="' + esc(el.id) + '"]');
      if (l && norm(l.innerText)) return norm(l.innerText);
    }
    const wrap = el.closest('label');
    if (wrap && norm(wrap.innerText)) return norm(wrap.innerText);
    const sib = el.nextElementSibling || el.previousElementSibling;
    if (sib && norm(sib.innerText)) return norm(sib.innerText);
    // A bare radio/checkbox with no value attribute reports "on"; never use it.
    if (norm(el.value) && el.value !== 'on') return norm(el.value);
    if (nested && norm(nested.value) && nested.value !== 'on') return norm(nested.value);
    const aria = el.getAttribute('aria-label');
    if (aria && norm(aria)) return norm(aria);
    const by = (el.getAttribute('aria-labelledby') || '').trim();
    if (by) {
      const parts = by.split(/\s+/).map((id) => {
        const n = document.getElementById(id);
        return n ? norm(n.innerText) : '';
      }).filter(Boolean);
      if (parts.length) return parts.join(' ');
    }
    return '';
  };

  const readValue = (el) => {
    const tag = el.tagName.toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'select') {
      if (isSelectPrompt(el)) return '';
      const opt = el.options ? el.options[el.selectedIndex] : null;
      return opt ? norm(opt.text || opt.value) : '';
    }
    if (type === 'checkbox' || role === 'checkbox') {
      const on = el.checked || el.getAttribute('aria-checked') === 'true';
      return on ? optionText(el) : '';
    }
    if (type === 'radio' || role === 'radio') {
      const on = el.checked || el.getAttribute('aria-checked') === 'true';
      return on ? optionText(el) : '';
    }
    return norm(el.value);
  };

  const record = (node, finished) => {
    const el = resolveControl(node);
    if (!el || !inScope(node, el)) return;
    const value = readValue(el);
    if (!value) return;  // ignore empty edits and unrelated blur events
    state.value = value;
    if (finished) state.done = true;
  };

  document.addEventListener('input', (e) => record(e.target, false), true);
  document.addEventListener('change', (e) => record(e.target, true), true);
  document.addEventListener('click', (e) => {
    // Read after the page's own click handler sets the control's checked state.
    const node = e.target;
    setTimeout(() => record(node, true), 0);
  }, true);
  document.addEventListener('focusout', (e) => record(e.target, true), true);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') record(e.target, true);
  }, true);
  return true;
}
"""

# Read the answer for the current question. It combines the value the watcher
# recorded from an edit with the *live* value of the question's control(s), so a
# field the human filled before (or without) a fresh edit event is still captured.
# ``done`` is true once an edit finished or a choice/select already holds a value.
_READ_FORM_ANSWER_JS = r"""
(markers, name) => {
  const list = (markers || []).map(String).filter(Boolean);
  const groupName = name ? String(name) : '';
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s;

  // A <select>'s prompt option ("Select an option") is not an answer (BUG-037).
  // Mirrors the watcher's helper: value="" + disabled, or prompt-looking text.
  const isSelectPrompt = (el) => {
    const opt = el && el.options ? el.options[el.selectedIndex] : null;
    if (!opt) return true;
    const value = norm(el.value || '');
    const text = norm(opt.text || opt.value);
    if (/^(?:please\s+)?(?:select|choose|pick)\b/i.test(text)) return true;
    if (opt.disabled && !value) return true;
    return !text && !value;
  };

  const resolveControl = (host) => {
    if (!host) return null;
    const tag = (host.tagName || '').toLowerCase();
    if (tag === 'label') {
      if (host.control) return host.control;
      if (host.htmlFor) {
        const f = document.getElementById(host.htmlFor);
        if (f) return f;
      }
      const inner = host.querySelector(
        'input,textarea,select,[role="radio"],[role="checkbox"]'
      );
      if (inner) return inner;
    }
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return host;
    const role = (host.getAttribute('role') || '').toLowerCase();
    if (role === 'radio' || role === 'checkbox') return host;
    return host.querySelector(
      'input,textarea,select,[role="radio"],[role="checkbox"]'
    ) || host;
  };

  const labelText = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria && norm(aria)) return norm(aria);
    const by = (el.getAttribute('aria-labelledby') || '').trim();
    if (by) {
      const parts = by.split(/\s+/).map((id) => {
        const n = document.getElementById(id);
        return n ? norm(n.innerText) : '';
      }).filter(Boolean);
      if (parts.length) return parts.join(' ');
    }
    if (el.labels && el.labels.length && norm(el.labels[0].innerText)) {
      return norm(el.labels[0].innerText);
    }
    if (el.id) {
      const l = document.querySelector('label[for="' + esc(el.id) + '"]');
      if (l && norm(l.innerText)) return norm(l.innerText);
    }
    const wrap = el.closest('label');
    if (wrap && norm(wrap.innerText)) return norm(wrap.innerText);
    if (norm(el.innerText)) return norm(el.innerText);
    // A styled native input often keeps its option text in a sibling span.
    const sib = el.nextElementSibling || el.previousElementSibling;
    if (sib && norm(sib.innerText)) return norm(sib.innerText);
    if (norm(el.value)) return norm(el.value);
    return '';
  };

  const optionText = (el) => {
    // A role=radio/checkbox container's own visible text is the option; LinkedIn
    // sets the container's aria-label to the *question*, not the option.
    if (norm(el.innerText)) return norm(el.innerText);
    const nested = el.querySelector ? el.querySelector('input') : null;
    const own = (el.labels && el.labels[0])
      || (nested && nested.labels && nested.labels[0]) || null;
    if (own && norm(own.innerText)) return norm(own.innerText);
    if (el.id) {
      const l = document.querySelector('label[for="' + esc(el.id) + '"]');
      if (l && norm(l.innerText)) return norm(l.innerText);
    }
    const wrap = el.closest('label');
    if (wrap && norm(wrap.innerText)) return norm(wrap.innerText);
    const sib = el.nextElementSibling || el.previousElementSibling;
    if (sib && norm(sib.innerText)) return norm(sib.innerText);
    // A bare radio/checkbox with no value attribute reports "on"; never use it.
    if (norm(el.value) && el.value !== 'on') return norm(el.value);
    if (nested && norm(nested.value) && nested.value !== 'on') return norm(nested.value);
    const aria = el.getAttribute('aria-label');
    if (aria && norm(aria)) return norm(aria);
    return labelText(el);
  };

  const readControl = (el) => {
    if (!el) return { value: '', atomic: false };
    const tag = el.tagName.toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'select') {
      if (isSelectPrompt(el)) return { value: '', atomic: true };
      const opt = el.options ? el.options[el.selectedIndex] : null;
      return { value: opt ? norm(opt.text || opt.value) : '', atomic: true };
    }
    if (type === 'checkbox' || role === 'checkbox') {
      const on = el.checked || el.getAttribute('aria-checked') === 'true';
      return { value: on ? optionText(el) : '', atomic: true };
    }
    if (type === 'radio' || role === 'radio') {
      const on = el.checked || el.getAttribute('aria-checked') === 'true';
      return { value: on ? optionText(el) : '', atomic: true };
    }
    return { value: norm(el.value), atomic: false };
  };

  const seen = [];
  const consider = (el) => {
    if (!el || seen.indexOf(el) !== -1) return '';
    seen.push(el);
    return readControl(el).value;
  };

  let live = '', atomic = false;
  // 1) The question's marked control(s): covers ``div[role=radio]`` and inputs.
  for (const m of list) {
    const host = document.querySelector('[data-autojob-fill="' + esc(m) + '"]');
    if (!host) continue;
    const value = consider(resolveControl(host));
    if (value) { live = value; atomic = true; break; }
  }
  // 2) Fall back to the group's controls by name: a native input keeps a stable
  //    ``name`` even when React re-renders the marked wrapper away. Read the
  //    wrapper (its text is the option) and the input itself.
  if (!live && groupName) {
    const selector = 'input[name="' + esc(groupName) + '"],'
      + '[role="radio"][name="' + esc(groupName) + '"],'
      + '[role="checkbox"][name="' + esc(groupName) + '"]';
    document.querySelectorAll(selector).forEach((el) => {
      if (live) return;
      // Prefer the wrapper (its visible text is the option) over the bare input.
      const wrapper = el.closest('[role="radio"], [role="checkbox"]') || el;
      const value = consider(wrapper) || consider(resolveControl(el));
      if (value) { live = value; atomic = true; }
    });
  }

  const state = window.__autojobFormAnswer || {};
  // Only trust a recorded edit when it was recorded for *this* question: a value
  // left over from another question's control must never answer this one
  // (BUG-037: the right-to-work choice leaked into the next question).
  const recorded = (state.scope || []).map(String).filter(Boolean);
  const sameScope = !recorded.length || list.join('|') === recorded.join('|');
  const eventValue = sameScope ? norm(state.value || '') : '';
  return JSON.stringify({
    value: eventValue || live,
    done: (sameScope && !!state.done) || (atomic && !!live)
  });
}
"""
