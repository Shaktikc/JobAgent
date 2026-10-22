"""Task 5: ask the human for unknown answers, remember them, and show UI feedback.

This module owns Task 5's ask-the-human flow, split out of
:mod:`src.tools.browser`:

1. Receive a form question the LLM (Task 4.1) could not answer from the store.
2. Show a visible browser banner saying the agent does not know the answer, pause
   the run, and read the answer the human types into (or chooses on) the form
   control itself. The answer is stored the moment it is seen (not only when the
   wait ends) and the banner confirms with a "saved" message, so nothing is lost
   to a timeout or a manual submit.
3. Remember the question -> answer mapping so Task 4.1 can reuse it next time.

The banner has no input: the human edits the real form control and this module
reads it. It watches only the control(s) of the question being asked, so an
unrelated edit is never mistaken for the answer. The interaction uses browser-use's
deterministic CDP actor API (``Page`` / ``Element``); no LLM is involved here.
"""

from __future__ import annotations

import asyncio
import re
import time

from src.configuration import Settings
from src.state import Task5Outcome
from src.tools.answers import normalize_question, save_answer
from src.tools.browser import _append_note, _loads, _safe
from src.tools.linkedin_status_overlay import emit_step

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
    box.setAttribute('aria-label', 'AutoJobApply needs an answer');
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
    heading.textContent = 'AutoJobApply does not know this answer';
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
      + 'The answer is saved as soon as you give it.';
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
    row.appendChild(skip);
    box.appendChild(heading);
    box.appendChild(q);
    box.appendChild(hintEl);
    box.appendChild(instruction);
    box.appendChild(status);
    box.appendChild(row);
    document.documentElement.appendChild(box);
    skip.addEventListener('click', () => box.setAttribute('data-autojob-state', 'skipped'));
  }
  if (!box.isConnected) document.documentElement.appendChild(box);
  try {
    if (typeof box.showPopover === 'function') box.showPopover();
  } catch (e) { /* already open, or unsupported: fixed + max z-index still applies */ }
  box.setAttribute('data-autojob-state', 'pending');
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
      if (!el.value) return { value: '', atomic: true };  // placeholder option
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
  const eventValue = norm(state.value || '');
  return JSON.stringify({
    value: eventValue || live,
    done: !!state.done || (atomic && !!live)
  });
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

# A question whose "label" is really a raw form id (e.g. ``radio-group-_r_1t_``)
# means the label could not be read from the markup.
_UNLABELED_QUESTION_RE = re.compile(r"radio-group[-_]|(?:^|[-_])r_[0-9a-z]+_", re.IGNORECASE)


def _looks_unlabeled(question: str) -> bool:
    """True when ``question`` is a raw form id rather than human-readable text."""
    text = (question or "").strip()
    return (not text) or bool(_UNLABELED_QUESTION_RE.search(text))


async def _dump_question_context(
    page, question: str, markers, name, field_type: str, settings: Settings, notify
) -> None:
    """Best-effort: save the markup around a question (unlabeled or a radio group)."""
    if not _looks_unlabeled(question) and field_type != "radio":
        return
    try:
        payload = _loads(
            await _safe(
                page.evaluate(_DUMP_HOSTS_JS, list(markers or []), str(name or "")), ""
            )
        )
        html = str(payload.get("html") or "")
        if not html:
            return
        settings.debug_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "_", question.lower()).strip("_")[:40] or "unknown"
        path = settings.debug_dir / f"task5_context_{slug}.html"
        path.write_text(html, encoding="utf-8")
        notify(f"Task 5: saved the form markup for {question!r} to {path}.")
    except OSError:
        return


async def _finish_question(page, answer: str) -> None:
    """Show the "saved" confirmation briefly, then close the banner."""
    await _safe(page.evaluate(_MARK_SAVED_JS, answer))
    if _SAVED_VISIBLE_SECONDS > 0:
        await asyncio.sleep(_SAVED_VISIBLE_SECONDS)
    await _safe(page.evaluate(_HIDE_UNKNOWN_JS))


async def ask_human_for_answer(
    page,
    question: str,
    field_type: str,
    hint: str,
    settings: Settings,
    notify,
    human: Task5Outcome | None = None,
    markers: list[str] | None = None,
    name: str | None = None,
) -> str | None:
    """Task 5: show a browser banner and read the human's answer from the form.

    Returns the answer the human typed into (or chose on) the form control, or
    ``None`` when the human skipped or the wait timed out empty. The run pauses
    here (polling the page) instead of guessing. The banner plainly states the
    agent does not know the answer and, for a choice field, lists the allowed
    options (``hint``). The banner has no input: the human edits the real form
    field and this reads it.

    ``markers`` are the form markers (``data-autojob-fill``) of the question's
    control(s). They scope the watcher so an unrelated edit is never captured.

    The answer is stored the moment it is seen — well before the wait ends — and
    the banner shows a "saved" confirmation so the human knows it was kept.
    """
    human = human if human is not None else Task5Outcome()
    human.enabled = True
    human.asked += 1
    await _safe(page.evaluate(_WATCH_FORM_ANSWER_JS, list(markers or [])))
    shown = await _safe(page.evaluate(_SHOW_UNKNOWN_JS, question, hint or ""))
    if not shown:
        human.timed_out += 1
        human.notes = _append_note(
            human.notes, f"could not show the answer banner for {question!r}"
        )
        return None

    kind = f" ({field_type})" if field_type else ""
    notify(
        f"Task 5: I do not know {question!r}{kind}; answer it in the form "
        "field in the browser."
    )
    emit_step(
        notify,
        f"Waiting for you - I do not know {question!r}{kind}; "
        "answer it in the form on the page.",
    )
    await _dump_question_context(
        page, question, markers, name, field_type, settings, notify
    )
    markers_arg = list(markers or [])
    name_arg = str(name or "")
    # The human often fills several fields at once. If the field for this question
    # already holds an answer, take it now instead of waiting for a fresh edit.
    pre = _loads(
        await _safe(page.evaluate(_READ_FORM_ANSWER_JS, markers_arg, name_arg), "")
    )
    pre_answer = str(pre.get("value") or "").strip()
    if pre_answer:
        _store_answer(settings, question, pre_answer, human)
        await _finish_question(page, pre_answer)
        human.answered += 1
        if question not in human.answered_questions:
            human.answered_questions.append(question)
        notify(f"Task 5: picked up your answer for {question!r} from the form.")
        return pre_answer

    deadline = time.monotonic() + settings.session.ask_timeout_seconds
    last_saved = ""
    while time.monotonic() < deadline:
        payload = _loads(await _safe(page.evaluate(_READ_UNKNOWN_JS), ""))
        if str(payload.get("state") or "") == "skipped":
            await _safe(page.evaluate(_HIDE_UNKNOWN_JS))
            human.skipped += 1
            notify(f"Task 5: you skipped {question!r}; leaving it unknown.")
            return None
        answer_payload = _loads(
            await _safe(page.evaluate(_READ_FORM_ANSWER_JS, markers_arg, name_arg), "")
        )
        answer = str(answer_payload.get("value") or "").strip()
        if answer and answer != last_saved:
            # Persist immediately, before the wait even finishes, so the answer is
            # never lost to a timeout, a skip, or a manual submit.
            _store_answer(settings, question, answer, human)
            last_saved = answer
            # Confirm in the banner that the answer has been saved.
            await _safe(page.evaluate(_MARK_SAVED_JS, answer))
        if answer and answer_payload.get("done"):
            await _finish_question(page, answer)
            human.answered += 1
            if question not in human.answered_questions:
                human.answered_questions.append(question)
            notify(f"Task 5: got an answer for {question!r} from the form.")
            return answer
        await asyncio.sleep(settings.session.ask_poll_seconds)

    if last_saved:
        # The human answered but never signalled they finished (e.g. no blur, or a
        # custom control): keep the answer we already stored and use it.
        await _finish_question(page, last_saved)
        human.answered += 1
        if question not in human.answered_questions:
            human.answered_questions.append(question)
        notify(f"Task 5: using the answer for {question!r} typed on the form.")
        return last_saved
    await _safe(page.evaluate(_HIDE_UNKNOWN_JS))
    human.timed_out += 1
    human.notes = _append_note(human.notes, f"timed out waiting for an answer to {question!r}")
    notify(f"Task 5: timed out waiting for an answer to {question!r}.")
    return None


def _store_answer(
    settings: Settings,
    question: str,
    answer: str,
    human: Task5Outcome | None,
) -> None:
    """Persist an answer the instant it is seen (Task 5's early save).

    The caller still records the answer through :func:`_remember_answer` when the
    wait returns; this early write is the safety net that guarantees an answer the
    human gave is kept even if the run stops before that. It writes silently (no
    duplicate note) and never raises into the wait.
    """
    if not normalize_question(question):
        return
    try:
        save_answer(settings.answers_file, question, answer)
    except OSError as exc:  # noqa: BLE001 - a failed early write must not stop the wait
        if human is not None:
            human.notes = _append_note(human.notes, f"could not save {question!r}: {exc}")


def _remember_answer(
    settings: Settings,
    answers: dict[str, str],
    human: Task5Outcome | None,
    question: str,
    answer: str,
) -> None:
    """Persist a human answer and update the in-memory store for this run.

    An existing mapping is only replaced when the human supplies a new answer here;
    the update is recorded explicitly in the Task 5 notes rather than silently.
    """
    key = normalize_question(question)
    previous = answers.get(key)
    answers[key] = answer
    try:
        save_answer(settings.answers_file, question, answer)
    except OSError as exc:  # noqa: BLE001 - a failed write must not stop the fill
        if human is not None:
            human.notes = _append_note(human.notes, f"could not save {question!r}: {exc}")
        return
    if human is not None:
        action = "updated the stored answer" if previous and previous != answer else "remembered"
        human.notes = _append_note(human.notes, f"{action} the answer for {question!r}")
