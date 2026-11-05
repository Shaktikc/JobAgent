"""Read visible, field-related rejection metadata from the current form only."""

from src.tools.browser import FIND_APPLY_ROOT_JS, _loads

_QUERY = r"""(fields) => {
  // __APPLY_ROOT__
  const root = findApplyRoot();
  if (!root) return JSON.stringify({issues: []});
  const visible = el => {
    if (!el || !el.getClientRects().length) return false;
    for (let node = el; node; node = node.parentElement) {
      const css = getComputedStyle(node);
      if (css.visibility === 'hidden' || css.display === 'none' || css.opacity === '0') {
        return false;
      }
    }
    return true;
  };
  const norm = value => (value || '').replace(/\s+/g, ' ').trim();
  const rejection = text => new RegExp(
    'invalid input|please (?:enter|select|provide)|\\brequired\\b|must be|exceeds|too long'
    + '|valid (?:number|email|value)|between \\d', 'i').test(text);
  const selectors = '[role="alert"],.artdeco-inline-feedback__message,'
    + '[data-testid*="helper-text"],[id*="error"],.artdeco-inline-feedback--error';
  const explicitError = node => !!node.closest('.artdeco-inline-feedback--error,'
    + '[data-test-form-element-error-messages],[data-testid*="error"]');
  const feedback = el => Array.from(el.querySelectorAll(selectors + ',p,span'))
    .filter(node => visible(node) && (node.matches(selectors)
      ? explicitError(node) || rejection(norm(node.innerText))
        || (el !== root && node.getAttribute('role') === 'alert')
      : /^(?:invalid input|this field is required|required)[.!]?$/i.test(norm(node.innerText))));
  const values = fields.filter(f => !['radio','checkbox'].includes(f.kind))
    .map(f => String(f.value || '')).concat(
    Array.from(root.querySelectorAll('input:not([type="radio"]):not([type="checkbox"]),'
      + 'select,textarea')).map(el => String(el.value || ''))
  ).filter(Boolean)
    .sort((a,b) => b.length - a.length);
  const redact = text => values.reduce(
    (result, value) => result.split(value).join('[redacted]'), text);
  const controls = fields.map(field => {
    const host = root.querySelector('[data-autojob-fill="' + field.marker + '"]');
    const el = host && (host.closest('[role="radio"],[role="checkbox"]')
      || host.control || host.querySelector('input,select,textarea') || host);
    return {field, host, el};
  });
  const sameQuestion = (a, b) => {
    if (a === b) return true;
    if (!['radio','checkbox'].includes(a.kind) || a.kind !== b.kind) return false;
    return a.question === b.question && !!a.question
      && (a.kind === 'checkbox' || a.name === b.name);
  };
  const owns = (box, field) => !controls.some(row => row.el && box.contains(row.el)
    && !sameQuestion(row.field, field));
  const ownsFeedback = (node, field) => {
    for (let box = node.parentElement; box && box !== root; box = box.parentElement) {
      if (controls.some(row => row.el && box.contains(row.el))) return owns(box, field);
    }
    return true; // An explicit reference to form-level feedback has no other local owner.
  };
  const used = new Set(), issues = [];
  for (const {field, host, el} of controls) {
    if (!visible(host) || !el) continue;
    const references = ((el.getAttribute('aria-describedby') || '') + ' '
      + (el.getAttribute('aria-errormessage') || '')).split(/\s+/).filter(Boolean);
    const errorId = el.getAttribute('aria-errormessage');
    let messages = references.map(id => document.getElementById(id))
      .filter(node => root.contains(node) && visible(node) && ownsFeedback(node, field)
        && (node.id === errorId
        || explicitError(node) || rejection(norm(node.innerText))
        || node.getAttribute('role') === 'alert'));
    let local = el.parentElement;
    for (let depth = 0; !messages.length && local && local !== root && depth < 16; depth++) {
      // Stop before borrowing another question's feedback.
      if (!owns(local, field)) break;
      messages = feedback(local);
      if (!messages.length && local.parentElement !== root) local = local.parentElement;
      else break;
    }
    const group = el.closest('fieldset,[role="group"],[role="radiogroup"]');
    const invalid = el.getAttribute('aria-invalid') === 'true' || el.matches(':user-invalid')
      || (group && owns(group, field) && group.getAttribute('aria-invalid') === 'true');
    if (!invalid && !messages.length) continue;
    messages.forEach(node => used.add(node));
    let limit = el.maxLength >= 0 ? el.maxLength : null;
    const counterText = [local && local.innerText,
      ...messages.map(node => node.innerText)].join(' ');
    const counter = norm(counterText).match(/\b\d+\s*\/\s*(\d+)\b/);
    if (limit === null && counter) limit = Number(counter[1]);
    const control = {...field, value: String(el.value || field.value || ''),
      maxlength: limit, minlength: el.minLength >= 0 ? el.minLength : null,
      min: el.getAttribute('min'), max: el.getAttribute('max'),
      step: el.getAttribute('step'), pattern: el.getAttribute('pattern'),
      inputmode: el.getAttribute('inputmode'), default_value: el.getAttribute('value')};
    issues.push({question: field.question || field.name || '', marker: field.marker,
      message: redact(norm(messages.map(node => node.innerText).join('; ')) || 'Invalid input'),
      field: control});
  }
  for (const node of feedback(root)) {
    if (used.has(node) || [...used].some(el => el.contains(node) || node.contains(el))) continue;
    issues.push({question: '', marker: '', message: redact(norm(node.innerText)), field: {}});
  }
  return JSON.stringify({issues});
} """.replace("// __APPLY_ROOT__", FIND_APPLY_ROOT_JS)


async def read_rejections(page, fields: list[dict]) -> list[dict]:
    """Runtime field values stay private to correction, outside outcome/log models."""
    payload = _loads(await page.evaluate(_QUERY, fields))
    return list(payload.get("issues") or [])
