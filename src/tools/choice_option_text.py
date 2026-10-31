"""Shared browser-side reader for a choice option's visible text.

LinkedIn renders screening questions in several layouts, and the option text is
not always in an associated ``label``. In the 2026 SDUI layout each radio is a
native input with an empty ``label[for]``, its ``aria-label`` set to the
**question**, and the visible option text ("Yes"/"No") in a sibling ``<p>`` of
the next ancestor. Reading the aria-label therefore stored the question itself as
the human's answer (BUG-082).

``CHOICE_OPTION_TEXT_JS`` defines ``_autojobOptionText(el, question)`` plus small
helpers. It is injected into the form-enumeration query, Task 5's answer
watcher/reader, and the checkbox-group scripts. It never falls back to
``aria-label`` because on LinkedIn that is the question. The snippet is
self-contained (its helpers are prefixed) so it can be concatenated inside any of
those IIFEs without colliding with their ``norm``/``esc`` helpers.
"""

from __future__ import annotations

CHOICE_OPTION_TEXT_JS = r"""
  const _autojobChoiceSelector =
    'input[type="radio"],input[type="checkbox"],[role="radio"],[role="checkbox"]';
  const _autojobNorm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const _autojobEsc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s;
  const _autojobQuestionKey = (s) =>
    _autojobNorm(s).toLowerCase().replace(/[\s*:?.!]+$/, '').trim();
  const _autojobCleanOption = (text, question) => {
    let value = _autojobNorm(text);
    const q = _autojobQuestionKey(question);
    if (!value) return '';
    if (q && _autojobQuestionKey(value) === q) return '';
    if (q && _autojobQuestionKey(value).startsWith(q)) {
      value = _autojobNorm(value.slice(q.length))
        .replace(/^[\s*:?.!]+/, '');
    }
    return value;
  };
  const _autojobResolveChoice = (el) => {
    if (!el || !el.closest) return el;
    const tag = (el.tagName || '').toLowerCase();
    if (tag === 'label') {
      if (el.control) return el.control;
      if (el.htmlFor) {
        const control = document.getElementById(el.htmlFor);
        if (control) return control;
      }
      const inner = el.querySelector('input,[role="radio"],[role="checkbox"]');
      if (inner) return inner;
    }
    return el;
  };
  const _autojobChoiceRowText = (el, question) => {
    let node = el.parentElement;
    for (let hops = 0; hops < 4 && node; hops++) {
      if (node.querySelectorAll
          && node.querySelectorAll(_autojobChoiceSelector).length > 1) break;
      const text = _autojobCleanOption(node.innerText, question);
      if (text) return text;
      node = node.parentElement;
    }
    return '';
  };
  const _autojobOptionText = (el, question) => {
    const control = _autojobResolveChoice(el);
    if (!control) return '';
    const tag = (control.tagName || '').toLowerCase();
    const role = (control.getAttribute('role') || '').toLowerCase();
    const type = (control.getAttribute('type') || '').toLowerCase();
    const isChoice = role === 'radio' || role === 'checkbox'
      || type === 'radio' || type === 'checkbox';
    if (!isChoice) return _autojobCleanOption(control.innerText, question);
    // A styled choice wrapper owns the visible option text (older SDUI layout).
    const own = _autojobCleanOption(control.innerText, question);
    if (own) return own;
    if (control.labels && control.labels.length) {
      for (const label of control.labels) {
        const text = _autojobCleanOption(label.innerText, question);
        if (text) return text;
      }
    }
    if (control.id) {
      const label = document.querySelector(
        'label[for="' + _autojobEsc(control.id) + '"]'
      );
      const text = _autojobCleanOption(label && label.innerText, question);
      if (text) return text;
    }
    // Newer layout: input + empty label in one row; option text is in a sibling
    // block of the next ancestor. Climb only while the ancestor holds this one
    // choice (never the whole group/question).
    const row = _autojobChoiceRowText(control, question);
    if (row) return row;
    for (const sibling of [control.nextElementSibling, control.previousElementSibling]) {
      const text = _autojobCleanOption(sibling && sibling.innerText, question);
      if (text) return text;
    }
    // A bare radio/checkbox with no value attribute reports "on"; never use it.
    if (_autojobNorm(control.value) && control.value !== 'on') {
      return _autojobNorm(control.value);
    }
    const nested = control.querySelector ? control.querySelector('input') : null;
    if (nested && _autojobNorm(nested.value) && nested.value !== 'on') {
      return _autojobNorm(nested.value);
    }
    // Never use aria-label: LinkedIn puts the *question* there, not the option.
    return '';
  };
  const _autojobControlForNode = (node) => {
    if (!node || !node.closest) return null;
    const choice = node.closest('[role="radio"], [role="checkbox"]');
    if (choice) return choice;
    const label = node.closest('label');
    if (label) {
      if (label.control) return label.control;
      if (label.htmlFor) {
        const control = document.getElementById(label.htmlFor);
        if (control) return control;
      }
      const inner = label.querySelector(
        'input,textarea,select,[role="radio"],[role="checkbox"]'
      );
      if (inner) return inner;
    }
    const direct = node.closest('input, textarea, select');
    if (direct) return direct;
    let scope = node.parentElement;
    for (let hops = 0; hops < 4 && scope; hops++) {
      if (!scope.querySelectorAll) break;
      const controls = scope.querySelectorAll(_autojobChoiceSelector);
      if (controls.length === 1) return controls[0];
      if (controls.length > 1) return null;
      scope = scope.parentElement;
    }
    return null;
  };
  const _autojobSharedRow = (el, scope) => {
    const allowed = (scope || []).map(String).filter(Boolean);
    if (!allowed.length || !el || !el.parentElement) return false;
    let node = el.parentElement;
    for (let hops = 0; hops < 4 && node; hops++) {
      if (node.querySelectorAll) {
        const marks = Array.from(node.querySelectorAll('[data-autojob-fill]'));
        if (marks.length) {
          // Accept only a marker for the question being asked, never another
          // question's option row (the BUG-037 leak guard).
          return marks.some(
            (mark) => allowed.indexOf(mark.getAttribute('data-autojob-fill')) !== -1
          );
        }
      }
      node = node.parentElement;
    }
    return false;
  };
"""

__all__ = ["CHOICE_OPTION_TEXT_JS"]
