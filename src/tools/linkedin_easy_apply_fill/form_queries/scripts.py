"""Task 4: the DOM query scripts injected into the open Easy Apply form.

Each query is a self-contained IIFE; :func:`_with_apply_root` injects the shared
``findApplyRoot()`` finder so the classic-modal and inline layouts share one code
path. The form is dynamic, so its fields, resume control (a radio list, a
``<select>``, a file input, or an "Upload resume" button that reveals one), and
buttons are discovered at runtime rather than assumed.

The async readers that wrap these scripts live in
:mod:`~src.tools.linkedin_easy_apply_fill.form_queries.readers`.
"""

from __future__ import annotations

from src.tools.browser import FIND_APPLY_ROOT_JS
from src.tools.choice_option_text import CHOICE_OPTION_TEXT_JS
from src.tools.forms import REQUIRED_MARKER_JS, STEP_IDENTITY_JS
from src.tools.linkedin_easy_apply_fill.checkbox_groups import GROUP_QUESTION_JS

# Enumerate the Easy Apply form's controls (Task 4). Each control gets a
# ``data-autojob-fill`` marker so it can be resolved back to a browser-use
# Element; radio/checkbox markers sit on the clickable label.
_ENUMERATE_FORM_QUERY = r"""
() => {
  const modal = findApplyRoot();
  if (!modal) return JSON.stringify({ open: false, title: '', step: '', fields: [] });

  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const titleEl = modal.querySelector('h3');
  const title = titleEl ? norm(titleEl.innerText) : '';
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s;
  // __AUTOJOB_GROUP_QUESTION__ (injected by _with_apply_root)

  const ownLabel = (el) => questionLabel(el, false);

  const clickTarget = (el) => {
    if (el.id) {
      const l = modal.querySelector('label[for="' + esc(el.id) + '"]');
      if (l) return l;
    }
    const wrap = el.closest('label');
    return wrap || el;
  };

  modal.querySelectorAll('[data-autojob-fill]').forEach(
    (el) => el.removeAttribute('data-autojob-fill')
  );

  const controls = modal.querySelectorAll(
    'input:not([type=hidden]):not([type=file]), textarea, select, '
    + '[role="radio"], [role="checkbox"]'
  );
  const fields = [];
  let i = 0;
  controls.forEach((el) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    let kind = 'input';
    if (tag === 'textarea') kind = 'textarea';
    else if (tag === 'select') kind = 'select';
    else if (role === 'radio' || type === 'radio') kind = 'radio';
    else if (role === 'checkbox' || type === 'checkbox') kind = 'checkbox';

    // The role=radio/checkbox wrapper is the real control; do not enumerate its
    // inner native input (or a nested wrapper) again.
    const isNativeChoice = tag === 'input' && (type === 'radio' || type === 'checkbox');
    if (isNativeChoice && el.closest('[role="radio"], [role="checkbox"]')) return;
    if ((role === 'radio' || role === 'checkbox')
        && el.parentElement && el.parentElement.closest('[role="radio"], [role="checkbox"]')) {
      return;
    }

    const isChoice = kind === 'radio' || kind === 'checkbox';
    const target = isChoice ? clickTarget(el) : el;
    if (!target.getClientRects().length) return; // skip controls on a hidden step
    const marker = 'f' + (i++);
    target.setAttribute('data-autojob-fill', marker);

    const options = [];
    if (tag === 'select') {
      Array.from(el.options).forEach((o) => options.push({ value: o.value, text: norm(o.text) }));
    }
    // A <select>'s visible choice, so its prompt ("Select an option", value="")
    // is not mistaken for an already-answered field (BUG-037).
    const selectedText = tag === 'select' && el.selectedIndex >= 0
      ? norm(el.options[el.selectedIndex].text) : '';
    // A wrapper's inner native input carries the group's name.
    let fieldName = el.getAttribute('name') || '';
    if (!fieldName) {
      const nested = el.querySelector('input[name]');
      if (nested) fieldName = nested.getAttribute('name') || '';
    }
    const question = questionLabel(el, isChoice);
    // The visible option text ("Yes"/"No"), never the control's aria-label:
    // LinkedIn puts the *question* there (BUG-082).
    let option = '';
    if (isChoice) {
      option = _autojobOptionText(el, question);
      if (!option) {
        // The last resort is still screened for a question echo (the label's
        // aria-label on LinkedIn is the question).
        option = _autojobCleanOption(ownLabel(el), question);
      }
    }
    fields.push({
      marker: marker,
      kind: kind,
      type: type || tag,
      name: fieldName,
      question: question,
      option: option,
      required: requiredOf(el, isChoice, question),
      checked: !!el.checked || el.getAttribute('aria-checked') === 'true'
        || !!(el.querySelector && el.querySelector('input:checked,[aria-checked="true"]')),
      value: norm(el.value || ''),
      selected_text: selectedText,
      options: options
    });
  });

  // A stable identity for the current step, so field-less review steps are told
  // apart while transient typeahead/status text is ignored (see STEP_IDENTITY_JS).
  const step = stepIdentity(modal);

  return JSON.stringify({ open: true, title: title, step: step, fields: fields });
}
"""

# Find the resume options already listed on the form plus any file input (Task 4).
# The resume control is dynamic: it may be a radio list, a ``<select>``, a file
# input, or an "Upload resume" button that reveals the file input only on click.
_RESUME_OPTIONS_QUERY = r"""
() => {
  const modal = findApplyRoot();
  if (!modal) {
    return JSON.stringify({
      options: [], fileInput: false, select: null, uploadButton: null
    });
  }

  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s;
  const ownLabel = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria && norm(aria)) return norm(aria);
    if (el.id) {
      const l = modal.querySelector('label[for="' + esc(el.id) + '"]');
      if (l && norm(l.innerText)) return norm(l.innerText);
    }
    const wrap = el.closest('label');
    if (wrap && norm(wrap.innerText)) return norm(wrap.innerText);
    const box = el.closest(
      '.fb-dash-form-element, .fb-form-element, .fb-form-element-wrapper, '
      + '.jobs-easy-apply-form-element, .jobs-easy-apply-form-section__grouping, '
      + '.jobs-easy-apply-form-section'
    );
    if (box) {
      const lab = box.querySelector(
        'label, .fb-dash-form-element__label, .fb-form-element-label'
      );
      if (lab && norm(lab.innerText)) return norm(lab.innerText);
    }
    const role = (el.getAttribute('role') || '').toLowerCase();
    if ((role === 'radio' || role === 'checkbox') && norm(el.innerText)) {
      return norm(el.innerText);
    }
    return '';
  };
  const clickTarget = (el) => {
    if (el.id) {
      const l = modal.querySelector('label[for="' + esc(el.id) + '"]');
      if (l) return l;
    }
    const wrap = el.closest('label');
    return wrap || el;
  };

  ['data-autojob-resume', 'data-autojob-resume-select', 'data-autojob-resume-upload']
    .forEach((attr) => modal.querySelectorAll('[' + attr + ']').forEach(
      (el) => el.removeAttribute(attr)
    ));
  modal.querySelectorAll('[data-autojob-file]').forEach(
    (el) => el.removeAttribute('data-autojob-file')
  );

  const options = [];
  let i = 0;
  modal.querySelectorAll('input[type="radio"], [role="radio"]').forEach((el) => {
    const text = ownLabel(el);
    const hay = (text + ' ' + (el.value || '') + ' ' + (el.name || '') + ' ' + (el.id || ''))
      .toLowerCase();
    if (/\.(pdf|docx|txt|md)\b/.test(text.toLowerCase()) || hay.includes('resume')) {
      const target = clickTarget(el);
      if (!target.getClientRects().length) return; // skip hidden steps
      const marker = 'r' + (i++);
      target.setAttribute('data-autojob-resume', marker);
      options.push({
        marker: marker,
        label: text,
        value: el.value || '',
        checked: !!el.checked || el.getAttribute('aria-checked') === 'true'
      });
    }
  });

  // A resume chooser rendered as a <select>.
  let select = null;
  modal.querySelectorAll('select').forEach((el) => {
    if (select) return;
    const label = ownLabel(el);
    const hay = (label + ' ' + (el.name || '') + ' ' + (el.id || '')).toLowerCase();
    const choices = Array.from(el.options).map(
      (o) => ({ value: o.value, text: norm(o.text) })
    );
    const looksLikeResume = hay.includes('resume')
      || choices.some((o) => /\.(pdf|docx|txt|md)\b/i.test(o.text));
    if (looksLikeResume && el.getClientRects().length) {
      const marker = 's' + (i++);
      el.setAttribute('data-autojob-resume-select', marker);
      select = { marker: marker, label: label, options: choices };
    }
  });

  const file = modal.querySelector('input[type="file"]');
  if (file) file.setAttribute('data-autojob-file', '1');

  // A button that reveals the file input (e.g. "Upload resume").
  let uploadButton = null;
  modal.querySelectorAll('button, [role="button"]').forEach((el) => {
    if (uploadButton) return;
    const text = norm(el.innerText) || norm(el.getAttribute('aria-label'));
    if (/upload|add resume|attach resume|choose file/i.test(text)
        && el.getClientRects().length) {
      const marker = 'u' + (i++);
      el.setAttribute('data-autojob-resume-upload', marker);
      uploadButton = { marker: marker, label: text };
    }
  });

  return JSON.stringify({
    options: options,
    fileInput: !!file,
    select: select,
    uploadButton: uploadButton
  });
}
"""

# List the modal's buttons so the agent can advance a form (never submit).
_FORM_BUTTONS_QUERY = r"""
() => {
  const modal = findApplyRoot();
  if (!modal) return JSON.stringify({ buttons: [] });

  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  modal.querySelectorAll('[data-autojob-btn]').forEach(
    (el) => el.removeAttribute('data-autojob-btn')
  );

  const buttons = [];
  let i = 0;
  modal.querySelectorAll('footer button, .artdeco-modal__actionbar button, button').forEach(
    (el) => {
      if (!el.getClientRects().length) return; // skip buttons from a hidden step
      const text = norm(el.innerText) || norm(el.getAttribute('aria-label'));
      if (!text) return;
      const marker = 'b' + (i++);
      el.setAttribute('data-autojob-btn', marker);
      buttons.push({ marker: marker, text: text, disabled: !!el.disabled });
    }
  );
  return JSON.stringify({ buttons: buttons });
}
"""


def _with_apply_root(query: str) -> str:
    """Make ``findApplyRoot()`` (and the group-question helper) available to a query.

    The three form queries are self-contained IIFEs, so the shared root finder
    (:data:`FIND_APPLY_ROOT_JS`) is injected where they resolve the form, and the
    choice-group question and required-marker helpers (``GROUP_QUESTION_JS`` and
    ``REQUIRED_MARKER_JS`` from forms) are injected where the query
    declares the placeholder. This keeps the classic-modal and inline layouts on
    one code path.
    """
    query = query.replace(
        "const modal = findApplyRoot();",
        FIND_APPLY_ROOT_JS + "\n  const modal = findApplyRoot();",
    )
    return query.replace(
        _GROUP_QUESTION_PLACEHOLDER,
        GROUP_QUESTION_JS + REQUIRED_MARKER_JS + STEP_IDENTITY_JS + CHOICE_OPTION_TEXT_JS,
    )


_GROUP_QUESTION_PLACEHOLDER = "// __AUTOJOB_GROUP_QUESTION__ (injected by _with_apply_root)"


_ENUMERATE_FORM_QUERY = _with_apply_root(_ENUMERATE_FORM_QUERY)
_RESUME_OPTIONS_QUERY = _with_apply_root(_RESUME_OPTIONS_QUERY)
_FORM_BUTTONS_QUERY = _with_apply_root(_FORM_BUTTONS_QUERY)
