"""Task 4: fill the open Easy Apply form and attach the resume (without submitting).

This module owns Task 4's interactive fill flow, split out of
:mod:`src.tools.browser`:

1. Enumerate the form's fields and controls (text inputs, selects, radio buttons,
   checkboxes, date pickers, and the resume upload control).
2. Fill every field whose answer is already known; leave unknown fields for
   Task 5 (or flag them), and attach the resume chosen by Task 3, preferring a
   resume already listed on the form over uploading a duplicate.
3. Advance through multi-step forms, stopping before **Submit application**.

The form is dynamic, so its steps, fields, and resume control (a radio list, a
``<select>``, a file input, or an "Upload resume" button that reveals one) are
discovered at runtime rather than assumed. Task 5's ask-the-human code lives in
:mod:`src.tools.browser` and is called from here when a question is unknown.

Steps 2-3 are driven by browser-use's LLM agent (see
:mod:`src.tools.agent_fill`): when a model and an OpenRouter key are configured,
the agent is the **sole** mechanism that decides which enumerated fields already
have a known answer and fills them, behind a navigation/submit guard. The
deterministic store fill is then disabled for that run; fields the agent leaves
empty are handed to Task 5. With no model configured the deterministic fill is
used instead (fully offline, no LLM involved).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.configuration import Settings
from src.state import FormField, Task4Outcome, Task5Outcome
from src.tools.agent_fill import fill_known_fields_with_agent
from src.tools.answers import lookup_answer
from src.tools.browser import (
    FIND_APPLY_ROOT_JS,
    _append_note,
    _first_element,
    _loads,
    _marker_element,
    _pace,
    _remember_answer,
    _safe,
    ask_human_for_answer,
)
from src.tools.forms import (
    answers_match,
    looks_like_next,
    looks_like_resume_field,
    pick_listed_resume,
    pick_next_button,
)

# How many steps of a multi-step Easy Apply form to walk before stopping. The
# form is dynamic, so this is only a safety cap: the walk stops as soon as there
# is no Next button or the step stops changing.
_MAX_FORM_STEPS = 10

# Enumerate the Easy Apply form's controls (Task 4). Each control gets a
# ``data-autojob-fill`` marker so it can be resolved back to a browser-use
# Element; radio/checkbox markers sit on the clickable label.
_ENUMERATE_FORM_QUERY = r"""
() => {
  const modal = findApplyRoot();
  if (!modal) return JSON.stringify({ open: false, title: '', fields: [] });

  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const titleEl = modal.querySelector('h3');
  const title = titleEl ? norm(titleEl.innerText) : '';
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s;

  const ownLabel = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria && norm(aria)) return norm(aria);
    if (el.placeholder && norm(el.placeholder)) return norm(el.placeholder);
    if (el.id) {
      const l = modal.querySelector('label[for="' + esc(el.id) + '"]');
      if (l && norm(l.innerText)) return norm(l.innerText);
    }
    const wrap = el.closest('label');
    if (wrap && norm(wrap.innerText)) return norm(wrap.innerText);
    const box = el.closest(
      '.fb-dash-form-element, .fb-form-element, .fb-form-element-wrapper, '
      + '.artdeco-text-input, .jobs-easy-apply-form-element, '
      + '.jobs-easy-apply-form-section__grouping, .jobs-easy-apply-form-section'
    );
    if (box) {
      const lab = box.querySelector(
        'label, .fb-dash-form-element__label, .fb-form-element-label, '
        + '.artdeco-text-input--label'
      );
      if (lab && norm(lab.innerText)) return norm(lab.innerText);
    }
    // A choice control rendered as a styled div shows its own option label as
    // its text content (e.g. <div role="radio"><span>Yes</span></div>).
    const role = (el.getAttribute('role') || '').toLowerCase();
    if ((role === 'radio' || role === 'checkbox') && norm(el.innerText)) {
      return norm(el.innerText);
    }
    return '';
  };

  const groupLabel = (el) => {
    const fs = el.closest('fieldset');
    if (fs) {
      const lg = fs.querySelector('legend');
      if (lg && norm(lg.innerText)) return norm(lg.innerText);
    }
    // The question label usually sits in an outer grouping/section container
    // that also wraps the controls. Walk outward and take the first container
    // that actually holds a question label.
    const boxes = [
      '.jobs-easy-apply-form-section__grouping',
      '.jobs-easy-apply-form-section',
      '.fb-form-element-wrapper',
      '.fb-form-element',
      '.fb-dash-form-element',
      '.jobs-easy-apply-form-element',
      '.artdeco-form-element',
    ];
    for (const sel of boxes) {
      const box = el.closest(sel);
      if (!box) continue;
      const lab = box.querySelector(
        'legend, .fb-form-element-label, .fb-dash-form-element__label, label'
      );
      if (lab && norm(lab.innerText)) return norm(lab.innerText);
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

    const isChoice = kind === 'radio' || kind === 'checkbox';
    const target = isChoice ? clickTarget(el) : el;
    if (!target.getClientRects().length) return; // skip controls on a hidden step
    const marker = 'f' + (i++);
    target.setAttribute('data-autojob-fill', marker);

    const options = [];
    if (tag === 'select') {
      Array.from(el.options).forEach((o) => options.push({ value: o.value, text: norm(o.text) }));
    }
    fields.push({
      marker: marker,
      kind: kind,
      type: type || tag,
      name: el.getAttribute('name') || '',
      question: isChoice ? (groupLabel(el) || ownLabel(el)) : ownLabel(el),
      option: isChoice ? ownLabel(el) : '',
      required: !!el.required || el.getAttribute('aria-required') === 'true',
      checked: !!el.checked || el.getAttribute('aria-checked') === 'true',
      value: norm(el.value || ''),
      options: options
    });
  });
  return JSON.stringify({ open: true, title: title, fields: fields });
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

# Set a text/textarea value the way React expects (native setter + events).
_FILL_INPUT_JS = r"""
(value) => {
  const proto = this.tagName === 'TEXTAREA'
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(this, value);
  this.dispatchEvent(new Event('input', { bubbles: true }));
  this.dispatchEvent(new Event('change', { bubbles: true }));
  return this.value;
}
"""

# Set a <select> value and fire the change event.
_FILL_SELECT_JS = r"""
(value) => {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
  setter.call(this, value);
  this.dispatchEvent(new Event('change', { bubbles: true }));
  return this.value;
}
"""


def _with_apply_root(query: str) -> str:
    """Make ``findApplyRoot()`` available inside a Task 4 query.

    The three form queries are self-contained IIFEs, so the shared root finder
    (:data:`FIND_APPLY_ROOT_JS`) is injected where they resolve the form. This
    keeps the classic-modal and inline layouts on one code path.
    """
    return query.replace(
        "const modal = findApplyRoot();",
        FIND_APPLY_ROOT_JS + "\n  const modal = findApplyRoot();",
    )


_ENUMERATE_FORM_QUERY = _with_apply_root(_ENUMERATE_FORM_QUERY)
_RESUME_OPTIONS_QUERY = _with_apply_root(_RESUME_OPTIONS_QUERY)
_FORM_BUTTONS_QUERY = _with_apply_root(_FORM_BUTTONS_QUERY)


async def read_form(page) -> tuple[bool, str, list[dict]]:
    """Return ``(form_open, step_title, fields)`` for the open form (Task 4)."""
    payload = _loads(await _safe(page.evaluate(_ENUMERATE_FORM_QUERY), ""))
    return (
        bool(payload.get("open")),
        str(payload.get("title") or ""),
        list(payload.get("fields") or []),
    )


async def enumerate_form_fields(page) -> tuple[bool, list[dict]]:
    """Return ``(form_open, fields)`` for the open Easy Apply form (Task 4)."""
    opened, _title, fields = await read_form(page)
    return opened, fields


async def read_resume_info(page) -> dict:
    """Return the resume controls: ``options``, ``fileInput``, ``select``, ``uploadButton``.

    The form is dynamic, so the resume control may be a radio list, a
    ``<select>``, a file input, or an upload button that reveals the file input.
    """
    payload = _loads(await _safe(page.evaluate(_RESUME_OPTIONS_QUERY), ""))
    return {
        "options": list(payload.get("options") or []),
        "fileInput": bool(payload.get("fileInput")),
        "select": payload.get("select") or None,
        "uploadButton": payload.get("uploadButton") or None,
    }


async def read_resume_options(page) -> tuple[list[dict], bool]:
    """Return ``(listed_resume_options, file_input_present)`` for the form (Task 4)."""
    info = await read_resume_info(page)
    return info["options"], info["fileInput"]


async def read_form_buttons(page) -> list[dict]:
    """Return the Easy Apply modal's buttons (Task 4)."""
    payload = _loads(await _safe(page.evaluate(_FORM_BUTTONS_QUERY), ""))
    return list(payload.get("buttons") or [])


# Placeholder values a <select> may show before a real choice is made. A select
# holding one of these is still unanswered; anything else is treated as answered.
_SELECT_PLACEHOLDERS = {
    "",
    "select",
    "select...",
    "select an option",
    "select one",
    "select option",
    "choose",
    "choose an option",
    "choose one",
    "none",
}


def _control_already_answered(field: dict) -> bool:
    """True when a form control already holds a real (non-placeholder) value.

    LinkedIn pre-fills controls from the profile (e.g. the "Email address" and
    "Phone country code" ``<select>``s). Those are already answered, so the agent
    must not ask the human about them or overwrite them with a guess.
    """
    kind = field.get("kind")
    if kind in {"radio", "checkbox"}:
        return bool(field.get("checked"))
    value = str(field.get("value") or "").strip()
    if not value:
        return False
    if kind == "select":
        return value.lower() not in _SELECT_PLACEHOLDERS
    return True


def _choice_hint(field: dict) -> str:
    """Human-readable list of a control's allowed options, for the banner."""
    choices = field.get("options") or []
    labels: list[str] = []
    for choice in choices:
        if isinstance(choice, dict):
            label = str(choice.get("text") or choice.get("value") or "").strip()
        else:
            label = str(choice).strip()
        if label:
            labels.append(label)
    if not labels:
        return ""
    return "One of: " + ", ".join(labels)


def _select_value_for(answer: str, options: list[dict]) -> str | None:
    """Resolve an answer to a ``<select>`` option value (matching text or value)."""
    for option in options:
        text = str(option.get("text") or "")
        value = str(option.get("value") or "")
        if answers_match(text, answer) or answers_match(value, answer):
            return value or text
    return None


async def _fill_field(element, field: dict, answer: str) -> tuple[bool, str]:
    """Fill one known field with the right control action; return ``(ok, error)``."""
    kind = field.get("kind")
    try:
        await _safe(element.evaluate("() => this.scrollIntoView({block: 'center'})"))
        if kind == "select":
            await element.evaluate(_FILL_SELECT_JS, str(answer))
        elif kind == "checkbox":
            if str(answer).strip().lower() in {"yes", "true", "1", "on"}:
                await element.check()
        elif kind == "radio":
            await element.click()
        else:
            await element.evaluate(_FILL_INPUT_JS, str(answer))
        return True, ""
    except Exception as exc:  # noqa: BLE001 - one bad field must not stop the run
        return False, f"{type(exc).__name__}: {exc}"


async def _fill_step(
    page,
    fields: list[dict],
    answers: dict[str, str],
    settings: Settings,
    ask=None,
    human: Task5Outcome | None = None,
    use_store: bool = True,
) -> tuple[int, int, list[str], list[FormField]]:
    """Fill the known fields of one form step; leave the rest unknown.

    ``ask`` is Task 5's optional async ``(question, field) -> answer | None``
    callable. When the store cannot answer a question (or a stored radio answer
    matches none of the step's options), it is used to ask the human; a returned
    answer is filled, remembered in the store, and reused for later occurrences.

    ``use_store`` is the deterministic known-answer path. It is disabled when
    browser-use's LLM agent is the **sole** mechanism for Task 4 steps 2-3: fields
    the agent already filled show up as "already answered", any other field is
    left to Task 5, and nothing is filled from the store here.
    """
    known = filled = 0
    unknown: list[str] = []
    records: list[FormField] = []

    radio_groups: dict[str, list[dict]] = {}
    others: list[dict] = []
    for field in fields:
        if field.get("kind") == "radio":
            key = field.get("name") or field.get("question") or field.get("marker")
            radio_groups.setdefault(key, []).append(field)
        else:
            others.append(field)

    async def _apply(record: FormField, field: dict, answer: str, source: str) -> None:
        nonlocal known, filled
        record.known = True
        record.value = answer
        record.answered_by = source
        element = await _marker_element(page, "data-autojob-fill", field["marker"])
        if element is None:
            record.error = "field element not found"
        else:
            ok, error = await _fill_field(element, field, answer)
            record.filled = ok
            record.error = error
        known += 1
        filled += 1 if record.filled else 0
        records.append(record)

    for key, group in radio_groups.items():
        question = next((g.get("question") for g in group if g.get("question")), "") or key
        options = [g.get("option", "") for g in group if g.get("option")]
        if looks_like_resume_field(question, options):
            continue  # the resume control is handled by _attach_resume
        record = FormField(
            question=question,
            field_type="radio",
            name=key,
            required=any(g.get("required") for g in group),
            options=options,
        )
        checked = next((g for g in group if g.get("checked")), None)
        if checked is not None:
            # Already selected on the form (e.g. a pre-filled choice): leave it be.
            record.known = True
            record.filled = True
            record.value = checked.get("option", "")
            record.answered_by = "form"
            known += 1
            filled += 1
            records.append(record)
            continue
        found = lookup_answer(answers, [question, key]) if use_store else None
        answer = found[1] if found else None
        source = "store" if found else "human"
        option = (
            next((g for g in group if answers_match(g.get("option", ""), answer)), None)
            if answer is not None
            else None
        )
        # Ask the human only when we have no usable answer: nothing stored, or a
        # stored answer that matches none of this step's options.
        if option is None and ask is not None:
            answered = await ask(question, {"type": "radio", "options": options})
            if answered is not None:
                _remember_answer(settings, answers, human, question, answered)
                answer, source = answered, "human"
                option = next(
                    (g for g in group if answers_match(g.get("option", ""), answered)), None
                )
        if option is not None:
            await _apply(record, option, answer, source)
            continue
        if answer is None:
            unknown.append(question)
            records.append(record)
            continue
        record.known = True
        record.value = answer
        record.answered_by = source
        record.error = "no option matched the answer"
        known += 1
        records.append(record)

    for field in others:
        question = field.get("question") or field.get("name") or f"field {field.get('marker')}"
        record = FormField(
            question=question,
            option=field.get("option", ""),
            field_type=field.get("type", ""),
            name=field.get("name", ""),
            required=bool(field.get("required")),
            options=[option.get("text", "") for option in field.get("options", [])],
        )
        if _control_already_answered(field):
            # The form already holds a real value (e.g. a pre-filled select): keep it.
            record.known = True
            record.filled = True
            record.value = str(field.get("value") or "")
            record.answered_by = "form"
            known += 1
            filled += 1
            records.append(record)
            continue
        found = lookup_answer(answers, [question, field.get("name", "")]) if use_store else None
        answer = found[1] if found else None
        source = "store" if found else "human"
        if answer is None and ask is not None:
            answered = await ask(question, field)
            if answered is not None:
                _remember_answer(settings, answers, human, question, answered)
                answer, source = answered, "human"
        if answer is None:
            unknown.append(question)
            records.append(record)
            continue
        if field.get("kind") == "select":
            # A <select> only accepts one of its option values, so map the answer
            # (which may be the visible option text) to the real value.
            resolved = _select_value_for(answer, field.get("options") or [])
            if resolved is None and field.get("options"):
                record.error = "the answer did not match any option"
                unknown.append(question)
                records.append(record)
                continue
            if resolved is not None:
                answer = resolved
        if field.get("kind") == "checkbox" and str(answer).strip().lower() in {
            "no",
            "false",
            "0",
            "off",
        }:
            record.known = True
            record.value = answer
            record.filled = True
            record.answered_by = source
            known += 1
            filled += 1
            records.append(record)
            continue
        await _apply(record, field, answer, source)

    await _pace(settings)
    return known, filled, unknown, records


async def upload_file_via_cdp(session, page, selector: str, file_path: str) -> None:
    """Attach ``file_path`` to the file input matching ``selector`` over CDP.

    Uses the page's own CDP session (``page.session_id``) so the element is
    resolved in the tab we are driving, and ``Runtime.evaluate`` to obtain the
    element's object id for ``DOM.setFileInputFiles``.
    """
    if not Path(file_path).is_file():
        raise RuntimeError(f"resume file does not exist: {file_path}")
    client = session.cdp_client
    session_id = await page.session_id
    await client.send.DOM.enable(session_id=session_id)
    expression = f"document.querySelector({json.dumps(selector)})"
    found = await client.send.Runtime.evaluate(
        params={"expression": expression, "returnByValue": False}, session_id=session_id
    )
    object_id = (found.get("result") or {}).get("objectId")
    if not object_id:
        raise RuntimeError(f"file input not found: {selector}")
    await client.send.DOM.setFileInputFiles(
        params={"files": [file_path], "objectId": object_id}, session_id=session_id
    )


async def _resume_file_selector(page) -> str | None:
    """CSS selector for the form's file input, if one is present on this step."""
    if await _first_element(page, ['[data-autojob-file="1"]']) is not None:
        return '[data-autojob-file="1"]'
    if await _first_element(page, ['input[type="file"]']) is not None:
        return 'input[type="file"]'
    return None


def _resume_listed_names(info: dict) -> list[str]:
    """Every resume name the form already lists (radio options and select choices)."""
    names = [option.get("label", "") for option in info.get("options", [])]
    select = info.get("select")
    if select:
        names += [choice.get("text", "") for choice in select.get("options", [])]
    return names


async def _attach_resume(
    page,
    session,
    resume_path: str,
    settings: Settings,
    outcome: Task4Outcome,
    notify,
) -> None:
    """Attach the Task 3 resume wherever it is on the dynamic form (Task 4).

    Prefers a resume already listed on the current step (a radio option or a
    ``<select>`` choice); otherwise uploads the file, clicking an "Upload
    resume" button first when that is what reveals the file input.
    """
    info = await read_resume_info(page)
    matched = pick_listed_resume(resume_path, _resume_listed_names(info))

    if matched:
        option = next((o for o in info.get("options", []) if o.get("label") == matched), None)
        if option is not None:
            element = await _marker_element(page, "data-autojob-resume", option["marker"])
            if element is not None:
                await _safe(element.click())
                if settings.session.post_click_wait_seconds:
                    await asyncio.sleep(settings.session.post_click_wait_seconds)
                outcome.resume_attached = True
                outcome.resume_selection = "listed"
                outcome.resume_listed_name = matched
                notify(f"Task 4: selected the listed resume {matched!r}.")
                return

        select = info.get("select")
        choice = (
            next((c for c in select["options"] if c.get("text") == matched), None)
            if select
            else None
        )
        if select is not None and choice is not None:
            element = await _marker_element(page, "data-autojob-resume-select", select["marker"])
            if element is not None:
                await element.evaluate(_FILL_SELECT_JS, str(choice["value"]))
                if settings.session.post_click_wait_seconds:
                    await asyncio.sleep(settings.session.post_click_wait_seconds)
                outcome.resume_attached = True
                outcome.resume_selection = "listed"
                outcome.resume_listed_name = matched
                notify(f"Task 4: selected the listed resume {matched!r}.")
                return

    selector = await _resume_file_selector(page)
    if selector is None and info.get("uploadButton"):
        upload = info["uploadButton"]
        element = await _marker_element(page, "data-autojob-resume-upload", upload["marker"])
        if element is not None:
            await _safe(element.click())
            if settings.session.post_click_wait_seconds:
                await asyncio.sleep(settings.session.post_click_wait_seconds)
            selector = await _resume_file_selector(page)

    if selector is None:
        # The form is dynamic, so the resume control may appear on a later step;
        # record it once (not on every step) but keep looking on subsequent steps.
        note = "no resume control found on this form step"
        if note not in outcome.notes:
            outcome.notes = _append_note(outcome.notes, note)
        return

    outcome.upload_attempted = True
    try:
        await upload_file_via_cdp(session, page, selector, resume_path)
    except Exception as exc:  # noqa: BLE001 - report and continue
        outcome.notes = _append_note(outcome.notes, f"resume upload failed: {exc}")
        return
    if settings.session.post_click_wait_seconds:
        await asyncio.sleep(settings.session.post_click_wait_seconds)
    outcome.resume_attached = True
    outcome.resume_selection = "uploaded"
    notify(f"Task 4: uploaded resume {Path(resume_path).name!r}.")


def _form_signature(title: str, fields: list[dict]) -> str:
    """A stable fingerprint of a form step, to detect that Next did not advance."""
    parts = [title or ""]
    for field in fields:
        parts.append(
            "|".join(str(field.get(key, "")) for key in ("kind", "question", "name", "option"))
        )
    return "\n".join(parts)


def _blocking_questions(records: list[FormField]) -> list[str]:
    """Required questions on a step that are still unanswered (they block Next)."""
    blocking: list[str] = []
    for record in records:
        if record.required and not record.known and record.question not in blocking:
            blocking.append(record.question)
    return blocking


def _blocked_note(prefix: str, blocking: list[str]) -> str:
    """A clear "why the form stopped" note, naming the required unknown answers."""
    if blocking:
        return (
            f"{prefix}; required questions are unanswered: "
            + ", ".join(blocking)
            + " - stopping before Submit"
        )
    return f"{prefix}; stopping before Submit"


async def _task4_on_page(
    page,
    session,
    resume_path: str | None,
    answers: dict[str, str],
    settings: Settings,
    notify,
    human: Task5Outcome | None = None,
) -> Task4Outcome:
    """Fill the open Easy Apply form and attach the resume, without submitting.

    The form is dynamic: its steps, fields, and resume control (radio list,
    ``<select>``, file input, or an upload button that reveals one) are
    discovered at runtime rather than assumed. The walk stops at the terminal
    step (only Submit is left), or as soon as a step fails to advance.

    Steps 2-3 are handled by browser-use's LLM agent when it is enabled; the
    deterministic store fill is then disabled so the agent is the sole filler.
    Task 5 rides along: when a question is unknown (including anything the agent
    left empty) and ``ask_human`` is on, the run pauses on a browser banner and
    reads the answer the human types into the form field. Answers are remembered
    so the same question is filled automatically next time. The optional
    ``human`` tracker records the questions asked, answered, skipped, and timed out.
    """
    outcome = Task4Outcome(resume_path=resume_path or "")
    human = human if human is not None else Task5Outcome()
    human.enabled = bool(settings.session.ask_human)

    asker = None
    if human.enabled:

        async def _ask_question(question: str, field: dict) -> str | None:
            return await ask_human_for_answer(
                page,
                question,
                field.get("type", ""),
                _choice_hint(field),
                settings,
                notify,
                human,
            )

        asker = _ask_question

    previous: str | None = None
    pending_advance = False
    blocking: list[str] = []

    for step in range(_MAX_FORM_STEPS):
        opened, title, fields = await read_form(page)
        if not opened:
            if step == 0:
                outcome.notes = _append_note(outcome.notes, "Easy Apply form was not found")
            break

        signature = _form_signature(title, fields)
        if pending_advance:
            if signature == previous:
                # The click did not move to a new step: stop instead of retrying
                # blindly, naming the required answers that are still unknown.
                outcome.notes = _append_note(
                    outcome.notes, _blocked_note("form did not advance to a new step", blocking)
                )
                break
            outcome.steps_advanced += 1
            pending_advance = False
        previous = signature

        outcome.form_open = True
        # Task 4 steps 2-3: browser-use's LLM agent is the SOLE mechanism that
        # decides which fields are already known (from the answer store) and fills
        # them. It runs behind a navigation/submit guard. When enabled, the
        # deterministic store fill below is disabled (`use_store=False`) so the
        # store is never applied as a fallback: fields the agent did not fill are
        # left to Task 5, which asks the human.
        agent_enabled = settings.agent_fill_enabled
        if agent_enabled:
            report = await fill_known_fields_with_agent(page, session, answers, settings, notify)
            if report is not None and report.note:
                outcome.notes = _append_note(outcome.notes, f"agent fill: {report.note}")
            # Re-read the step so the checks below see the agent's edits (fresh
            # values/checked state) instead of the pre-fill snapshot.
            opened, title, fields = await read_form(page)
            if not opened:
                outcome.notes = _append_note(
                    outcome.notes, "Easy Apply form closed during the agent fill"
                )
                break

        outcome.fields_enumerated += len(fields)
        known, filled, unknown, records = await _fill_step(
            page, fields, answers, settings, ask=asker, human=human, use_store=not agent_enabled
        )
        outcome.known_fields += known
        outcome.filled_fields += filled
        outcome.unknown_fields.extend(unknown)
        outcome.fields.extend(records)

        if resume_path and not outcome.resume_attached:
            await _attach_resume(page, session, resume_path, settings, outcome, notify)

        buttons = await read_form_buttons(page)
        button = pick_next_button(buttons)
        if button is None:
            # No enabled Next/Continue on this step. Say *why* we stopped: a
            # disabled navigation button usually means a required answer is
            # missing, otherwise this is the terminal step (only Submit remains).
            blocking = _blocking_questions(records)
            if any(looks_like_next(b.get("text", "")) for b in buttons):
                outcome.notes = _append_note(
                    outcome.notes, _blocked_note("the only navigation button is disabled", blocking)
                )
            else:
                outcome.notes = _append_note(
                    outcome.notes, "reached the last step (only Submit remains)"
                )
            break

        element = await _marker_element(page, "data-autojob-btn", button["marker"])
        if element is None:
            outcome.notes = _append_note(
                outcome.notes, "navigation button disappeared before it could be clicked"
            )
            break

        blocking = _blocking_questions(records)
        notify(f"Task 4: advancing form step via {button.get('text')!r}.")
        await _safe(element.click())
        pending_advance = True
        if settings.session.post_click_wait_seconds:
            await asyncio.sleep(settings.session.post_click_wait_seconds)
        await _pace(settings)

    outcome.page_url = await _safe(page.get_url(), None)
    return outcome


def _task4_ok(outcome: Task4Outcome) -> bool:
    return bool(
        outcome.form_open
        and outcome.resume_attached
        and outcome.filled_fields == outcome.known_fields
        and not outcome.submitted
    )
