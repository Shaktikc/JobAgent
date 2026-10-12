"""Task 5: ask the human for unknown answers, remember them, and show UI feedback.

This module owns Task 5's ask-the-human flow, split out of
:mod:`src.tools.browser`:

1. Receive a form question the LLM (Task 4.1) could not answer from the store.
2. Show a visible browser banner saying the agent does not know the answer, pause
   the run, and read the answer the human types into the form field itself.
3. Remember the question -> answer mapping so Task 4.1 can reuse it next time.

The banner has no input: the human edits the real form control and this module
reads it. The interaction uses browser-use's deterministic CDP actor API
(``Page`` / ``Element``); no LLM is involved here.
"""

from __future__ import annotations

import asyncio
import time

from src.configuration import Settings
from src.state import Task5Outcome
from src.tools.answers import normalize_question, save_answer
from src.tools.browser import _append_note, _loads, _safe

# Task 5: a visible banner that tells the human the agent cannot answer a
# question and asks them to type the answer into the form field itself. The
# question text is set via ``textContent`` so page content can never inject
# markup. The banner records its state in ``data-autojob-state`` (``pending`` /
# ``skipped``) so the agent can poll it without blocking the page. There is no
# input in the banner: the answer is read from the form control the human edits.
_SHOW_UNKNOWN_JS = r"""
(question, hint) => {
  let box = document.getElementById('autojob-unknown');
  if (!box) {
    box = document.createElement('div');
    box.id = 'autojob-unknown';
    box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-label', 'AutoJobApply needs an answer');
    box.style.cssText = [
      'position:fixed', 'right:24px', 'bottom:24px', 'z-index:2147483647',
      'max-width:420px', 'background:#ffffff', 'color:#1a1a1a',
      'border:2px solid #b24020', 'border-radius:8px',
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
      'Type your answer in the form field on the page, then click away to confirm.';
    instruction.style.cssText = 'margin-bottom:8px;color:#555;font-size:13px';
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
    box.appendChild(row);
    document.body.appendChild(box);
    skip.addEventListener('click', () => box.setAttribute('data-autojob-state', 'skipped'));
  }
  box.setAttribute('data-autojob-state', 'pending');
  const q = document.getElementById('autojob-unknown-question');
  if (q) q.textContent = question || 'this question';
  const hintEl = document.getElementById('autojob-unknown-hint');
  if (hintEl) {
    hintEl.textContent = hint || '';
    hintEl.style.display = hint ? 'block' : 'none';
  }
  return true;
}
"""

# Task 5: watch the form for the human's answer. The banner has no input, so the
# human types into the actual form control; this records the edited value on the
# page and flags when the edit is finished (a change/blur or Enter). A single
# document-level listener is installed once and reset for each question, so the
# agent can poll the value without blocking.
_WATCH_FORM_ANSWER_JS = r"""
() => {
  const KEY = '__autojobFormAnswer';
  const previous = window[KEY];
  if (previous && previous.installed) {
    previous.value = '';
    previous.done = false;
    return true;
  }
  const state = { installed: true, value: '', done: false };
  window[KEY] = state;

  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s;

  const isControl = (el) => {
    if (!el || !el.tagName) return false;
    const tag = el.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
    const role = (el.getAttribute('role') || '').toLowerCase();
    return role === 'radio' || role === 'checkbox';
  };

  const labelText = (el) => {
    if (el.id) {
      const l = document.querySelector('label[for="' + esc(el.id) + '"]');
      if (l && norm(l.innerText)) return norm(l.innerText);
    }
    const wrap = el.closest('label');
    if (wrap && norm(wrap.innerText)) return norm(wrap.innerText);
    return '';
  };

  const readValue = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'select') {
      const opt = el.options ? el.options[el.selectedIndex] : null;
      return opt ? norm(opt.text || opt.value) : '';
    }
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (type === 'checkbox') return el.checked ? 'Yes' : '';
    if (type === 'radio') return el.checked ? (labelText(el) || norm(el.value)) : '';
    return norm(el.value);
  };

  const record = (el, finished) => {
    if (!isControl(el)) return;
    const value = readValue(el);
    if (!value) return;  // ignore empty edits and unrelated blur events
    state.value = value;
    if (finished) state.done = true;
  };

  document.addEventListener('input', (e) => record(e.target, false), true);
  document.addEventListener('change', (e) => record(e.target, true), true);
  document.addEventListener('focusout', (e) => record(e.target, true), true);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') record(e.target, true);
  }, true);
  return true;
}
"""

# Read the answer the human typed into the form (value + whether the edit is done).
_READ_FORM_ANSWER_JS = r"""
() => {
  const state = window.__autojobFormAnswer;
  if (!state) return JSON.stringify({ value: '', done: false });
  return JSON.stringify({ value: state.value || '', done: !!state.done });
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


async def ask_human_for_answer(
    page,
    question: str,
    field_type: str,
    hint: str,
    settings: Settings,
    notify,
    human: Task5Outcome | None = None,
) -> str | None:
    """Task 5: show a browser banner and read the human's answer from the form.

    Returns the answer the human typed into the form control, or ``None`` when the
    human skipped or the wait timed out. The run pauses here (polling the page)
    instead of guessing. The banner plainly states the agent does not know the
    answer and, for a choice field, lists the allowed options (``hint``). The
    banner has no input: the human edits the real form field and this reads it.
    """
    human = human if human is not None else Task5Outcome()
    human.enabled = True
    human.asked += 1
    await _safe(page.evaluate(_WATCH_FORM_ANSWER_JS))
    shown = await _safe(page.evaluate(_SHOW_UNKNOWN_JS, question, hint or ""))
    if not shown:
        human.timed_out += 1
        human.notes = _append_note(
            human.notes, f"could not show the answer banner for {question!r}"
        )
        return None

    kind = f" ({field_type})" if field_type else ""
    notify(
        f"Task 5: I do not know {question!r}{kind}; type the answer in the form "
        "field in the browser."
    )
    deadline = time.monotonic() + settings.session.ask_timeout_seconds
    while time.monotonic() < deadline:
        payload = _loads(await _safe(page.evaluate(_READ_UNKNOWN_JS), ""))
        if str(payload.get("state") or "") == "skipped":
            await _safe(page.evaluate(_HIDE_UNKNOWN_JS))
            human.skipped += 1
            notify(f"Task 5: you skipped {question!r}; leaving it unknown.")
            return None
        answer_payload = _loads(await _safe(page.evaluate(_READ_FORM_ANSWER_JS), ""))
        answer = str(answer_payload.get("value") or "").strip()
        if answer and answer_payload.get("done"):
            await _safe(page.evaluate(_HIDE_UNKNOWN_JS))
            human.answered += 1
            if question not in human.answered_questions:
                human.answered_questions.append(question)
            notify(f"Task 5: got an answer for {question!r} from the form.")
            return answer
        await asyncio.sleep(settings.session.ask_poll_seconds)

    await _safe(page.evaluate(_HIDE_UNKNOWN_JS))
    human.timed_out += 1
    human.notes = _append_note(human.notes, f"timed out waiting for an answer to {question!r}")
    notify(f"Task 5: timed out waiting for an answer to {question!r}.")
    return None


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
