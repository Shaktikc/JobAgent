"""Task 13/17: runtime discovery snippets for the **Date posted** filter.

The scripts tag controls with ``data-autojob-*`` attributes so the caller can
resolve them back to browser-use ``Element`` handles. They discover the filter
pill, the popover's range options, and the **Show results** button by their
visible/accessible labels — never by a fixed index or hashed CSS class.
"""

from __future__ import annotations

# Locate the "Date posted" pill. Scan visible interactive controls and return
# their best accessible label; the pure predicate picks the filter in Python.
_DATE_FILTER_QUERY = r"""
() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-autojob-date]').forEach(
    (el) => el.removeAttribute('data-autojob-date')
  );
  const controls = document.querySelectorAll(
    'button, a, [role="button"], [role="radio"], [role="combobox"], '
    + 'input[type="button"], input[type="submit"]'
  );
  const out = [];
  let i = 0;
  controls.forEach((el) => {
    if (!el.getClientRects().length) return; // skip hidden controls
    const label = norm(
      el.getAttribute('aria-label') || el.innerText
      || el.getAttribute('title') || el.value || ''
    );
    if (!label) return;
    const marker = 'd' + (i++);
    el.setAttribute('data-autojob-date', marker);
    out.push({
      marker: marker,
      label: label,
      checked: el.getAttribute('aria-checked') === 'true'
        || el.getAttribute('aria-pressed') === 'true'
        || el.checked === true
    });
  });
  return JSON.stringify({ controls: out });
}
"""

# Locate the open popover's range options. Radio inputs are preferred (their
# associated <label> is the click target); role=radio/menuitemradio and plain
# labels cover variants without a native input. The filter pill itself is never
# returned: it carries data-autojob-date from the finder above.
_DATE_OPTIONS_QUERY = r"""
() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const ranges = ['past 24 hours', 'past week', 'past month'];
  const isRange = (label) => {
    const text = norm(label).replace(/\.$/, '').replace(/\s+filter$/i, '').toLowerCase();
    return ranges.indexOf(text) !== -1;
  };
  document.querySelectorAll('[data-autojob-date-option]').forEach(
    (el) => el.removeAttribute('data-autojob-date-option')
  );
  const out = [];
  const seen = new Set();
  const add = (el, label, checked, value) => {
    if (!el || seen.has(el)) return;
    if (el.hasAttribute('data-autojob-date')) return; // never the filter pill
    if (!el.getClientRects().length) return;          // skip hidden options
    const text = norm(label);
    if (!isRange(text)) return;
    seen.add(el);
    const marker = 'o' + out.length;
    el.setAttribute('data-autojob-date-option', marker);
    out.push({
      marker: marker,
      label: text,
      checked: checked === true,
      value: value || ''
    });
  };
  document.querySelectorAll('input[type="radio"]').forEach((input) => {
    let label = norm(input.getAttribute('aria-label')) || norm(input.value);
    let labelled = null;
    if (input.id && typeof CSS !== 'undefined' && CSS.escape) {
      labelled = document.querySelector('label[for="' + CSS.escape(input.id) + '"]');
      if (labelled) label = norm(labelled.innerText) || label;
    }
    const checked = input.checked === true || input.getAttribute('aria-checked') === 'true';
    if (isRange(label)) add(labelled || input, label, checked, input.value || '');
  });
  document.querySelectorAll('[role="radio"], [role="menuitemradio"], label, button')
    .forEach((el) => {
      const label = norm(el.getAttribute('aria-label') || el.innerText || '');
      const checked = el.getAttribute('aria-checked') === 'true'
        || el.getAttribute('aria-pressed') === 'true'
        || !!(el.querySelector && el.querySelector('input[type="radio"]:checked'));
      add(el, label, checked, '');
    });
  return JSON.stringify({ options: out });
}
"""

# The popover's apply control. Exact normalized label so a job card's text or a
# "Show more" control is never clicked.
_SHOW_RESULTS_QUERY = r"""
() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase()
    .replace(/\.$/, '');
  document.querySelectorAll('[data-autojob-date-apply]').forEach(
    (el) => el.removeAttribute('data-autojob-date-apply')
  );
  const controls = document.querySelectorAll(
    'button, [role="button"], input[type="button"], input[type="submit"]'
  );
  for (const el of controls) {
    if (!el.getClientRects().length) continue;
    const label = norm(el.getAttribute('aria-label') || el.innerText || el.value || '');
    if (label !== 'show results' && label !== 'apply filter') continue;
    el.setAttribute('data-autojob-date-apply', 'apply');
    return JSON.stringify({ marker: 'apply' });
  }
  return JSON.stringify({ marker: null });
}
"""


__all__ = [
    "_DATE_FILTER_QUERY",
    "_DATE_OPTIONS_QUERY",
    "_SHOW_RESULTS_QUERY",
]
