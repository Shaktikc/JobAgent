"""Task 4/5: answer a **checkbox (multi-select)** question as one group.

LinkedIn renders a "select all that apply" screening question as a set of
``[role="checkbox"]`` options that share one group. The fill used to enumerate
each option as its *own* question, which broke it three ways:

* the group's real question was lost (the option text was read as the question),
* Task 5's answer watcher was scoped to a **single** option, so ticking any other
  option was never captured and the answer was never saved, and
* a stored answer could not tick a box (only a yes/no value was applied).

This module owns the whole group: it resolves the group's question in the page
(:data:`GROUP_QUESTION_JS`, injected into the enumeration query), reads every
ticked option from the live form (:data:`READ_GROUP_TICKS_JS`), matches an answer
to the group's options, and applies it by ticking the matching boxes. It also
re-resolves a **radio** group by its stable ``name`` when React re-renders the
marked wrapper away (:func:`remark_radio_by_name`, BUG-057). Everything here is
best-effort: a missing element or a failed read leaves the question for
Task 5 rather than mis-filling the form.
"""

from __future__ import annotations

import asyncio
import re
import time

from src.configuration import Settings
from src.state import FormField, Task5Outcome
from src.tools.browser import _loads, _safe
from src.tools.forms import answers_match
from src.tools.job_context_answers import record_decision
from src.tools.linkedin_ask_human import _remember_answer

# Injected into the form-enumeration query (see
# :mod:`~src.tools.linkedin_easy_apply_fill.form_queries.scripts`) to resolve the
# question of a choice group when the known container selectors miss it (LinkedIn
# uses hashed class names). It needs ``modal``, ``norm`` and ``esc`` from the
# query's own scope, so it is injected rather than imported.
GROUP_QUESTION_JS = r"""const firstTextWithoutControls = (node) => {
    const CONTROL = '[role="radio"],[role="checkbox"],input,select,textarea,button';
    if (!node.querySelector(CONTROL)) return norm(node.innerText);
    const kids = node.querySelectorAll('span,p,label,legend,h1,h2,h3,h4,h5,h6,div');
    for (const kid of kids) {
      if (kid.querySelector(CONTROL)) continue;
      const text = norm(kid.innerText);
      if (text) return text;
    }
    return '';
  };

  const groupQuestionFromOptions = (el) => {
    // The group element's own label attributes (React Aria points them at the
    // question element).
    const group = el.closest('[role="radiogroup"], [role="group"], fieldset');
    if (group) {
      const by = (group.getAttribute('aria-labelledby') || '').trim();
      if (by) {
        const parts = by.split(/\s+/).map((id) => {
          const n = modal.querySelector('#' + esc(id));
          return n ? norm(n.innerText) : '';
        }).filter(Boolean);
        if (parts.length) return parts.join(' ');
      }
      // LinkedIn's SDUI checkbox group is a bare <fieldset> (no legend, no
      // aria-label) with the question in a <p> just above it — inside the field's
      // own wrapper, or directly in the modal's scroller. Without this the option's
      // own text became the question, so every option was a separate question
      // (BUG-059).
      const host = group.parentElement;
      if (host && host !== modal) {
        const near = Array.from(host.querySelectorAll('legend, p'))
          .find((node) => !group.contains(node));
        if (near && norm(near.innerText)) return norm(near.innerText);
      }
      const prev = group.previousElementSibling;
      if (prev && norm(prev.innerText) && !prev.querySelector(
        '[role="radio"],[role="checkbox"],input,select,textarea'
      )) return norm(prev.innerText);
    }
    // Walk up to the ancestor that holds the whole option list, then read the
    // text that precedes the options: the question is rendered just above them.
    let box = el.parentElement;
    for (let hops = 0; box && box !== modal && hops < 8; hops++) {
      if (box.querySelectorAll(
        '[role="radio"],[role="checkbox"],input[type="radio"],input[type="checkbox"]'
      ).length > 1) break;
      box = box.parentElement;
    }
    if (!box || box === modal) return '';
    const texts = [];
    const siblings = [];
    for (let node = box.previousElementSibling; node; node = node.previousElementSibling) {
      siblings.unshift(node);
    }
    for (const node of siblings) {
      const text = firstTextWithoutControls(node);
      if (text) texts.push(text);
    }
    const looksLikeQuestion = (text) => text.includes('?') || /[*]\s*$/.test(text);
    return texts.find(looksLikeQuestion) || texts[0] || '';
  };"""

# Every option ticked in the group, in form order. A wrapper's checked state may
# live on a nested ``<input>``, and its visible text on a nested ``<p>``.
READ_GROUP_TICKS_JS = r"""
(markers) => {
  const list = (markers || []).map(String).filter(Boolean);
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const optionText = (option) => {
    if (norm(option.innerText)) return norm(option.innerText);
    const nested = option.querySelector('input');
    const own = (option.labels && option.labels[0])
      || (nested && nested.labels && nested.labels[0]) || null;
    if (own && norm(own.innerText)) return norm(own.innerText);
    if (nested && norm(nested.value) && nested.value !== 'on') return norm(nested.value);
    return '';
  };
  const isOn = (el) => !!(el.checked || el.getAttribute('aria-checked') === 'true'
    || (el.querySelector && el.querySelector('input:checked,[aria-checked="true"]')));
  const selected = [];
  for (const marker of list) {
    const host = document.querySelector('[data-autojob-fill="' + marker + '"]');
    if (!host || !isOn(host)) continue;
    const text = optionText(host);
    if (text && selected.indexOf(text) === -1) selected.push(text);
  }
  return JSON.stringify({ selected: selected });
}
"""

# Re-resolve a *radio* group by its stable ``name`` and re-mark the option that
# matches the answer. React re-renders the wrapper that carried
# ``data-autojob-fill`` away (a human edit or the group's own state change), so
# the cached marker goes stale even though the native input keeps its ``name``.
# The fill uses this to recover the control (BUG-057), mirroring the name-based
# fallback Task 5's answer reader already relies on.
REMARK_RADIO_BY_NAME_JS = r"""
(groupName, answer, marker) => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s;
  const name = norm(groupName);
  if (!name) return JSON.stringify({ ok: false });
  const selector = 'input[type="radio"][name="' + esc(name) + '"],'
    + '[role="radio"][name="' + esc(name) + '"]';
  const controls = Array.from(document.querySelectorAll(selector));
  if (!controls.length) return JSON.stringify({ ok: false });
  const optionText = (el) => {
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
    if (norm(el.value) && el.value !== 'on') return norm(el.value);
    if (nested && norm(nested.value) && nested.value !== 'on') return norm(nested.value);
    return '';
  };
  const wrapper = (el) => el.closest('[role="radio"]') || el;
  const want = norm(answer).toLowerCase();
  const labelOf = (el) => norm(optionText(wrapper(el))).toLowerCase();
  const match = controls.find((el) => labelOf(el) === want)
    || controls.find((el) => {
      const text = labelOf(el);
      return !!text && !!want && (text.includes(want) || want.includes(text));
    });
  if (!match) return JSON.stringify({ ok: false });
  wrapper(match).setAttribute('data-autojob-fill', String(marker));
  return JSON.stringify({ ok: true });
}
"""

# A group answer may list several options ("A, B"); split on commas/semicolons.
_SPLIT_RE = re.compile(r"[;,]")


def group_counts(fields: list[dict]) -> dict[str, dict[str, int]]:
    """How often each checkbox ``name`` / ``question`` appears on the step."""
    counts: dict[str, dict[str, int]] = {"name": {}, "question": {}}
    for field in fields:
        if field.get("kind") != "checkbox":
            continue
        for kind in ("name", "question"):
            value = str(field.get(kind) or "")
            if value:
                counts[kind][value] = counts[kind].get(value, 0) + 1
    return counts


def group_key(field: dict, counts: dict[str, dict[str, int]]) -> str:
    """The key a checkbox option shares with the rest of its group.

    Prefer the shared ``name`` (LinkedIn groups its options that way); when every
    option carries its own name, fall back to the shared question text. A lone
    option is its own group.
    """
    name = str(field.get("name") or "")
    question = str(field.get("question") or "")
    if name and counts.get("name", {}).get(name, 0) > 1:
        return f"name:{name}"
    if question and counts.get("question", {}).get(question, 0) > 1:
        return f"question:{question}"
    return f"field:{field.get('marker')}"


def selected_options(answer: str | None, options: list[str]) -> list[str]:
    """The group's option labels that ``answer`` selects (empty when none do)."""
    text = (answer or "").strip()
    if not text or not options:
        return []
    parts = [part.strip() for part in _SPLIT_RE.split(text) if part.strip()]
    selected: list[str] = []
    for option in options:
        if not option:
            continue
        if any(answers_match(option, part) or answers_match(part, option) for part in parts):
            selected.append(option)
    if not selected and len(options) == 1 and text.lower() in {"yes", "y", "true", "1", "on"}:
        # A single checkbox asked as a yes/no question ("I agree", ...).
        selected.append(options[0])
    return selected


def selects_option(answer: str | None, option: str) -> bool:
    """True when ``answer`` selects the checkbox labelled ``option``."""
    text = (answer or "").strip()
    if not text:
        return False
    if answers_match(option, text) or answers_match(text, option):
        return True
    return text.lower() in {"yes", "y", "true", "1", "on"}


async def read_ticked_options(
    page, markers: list[str], *, settle_seconds: float = 0.8, max_seconds: float = 4.0
) -> list[str]:
    """Every option ticked in the group, after a short settle.

    A multi-select is usually ticked one box at a time, so the ticks are read
    until the set stops changing (bounded by ``max_seconds``), which captures the
    whole selection rather than only the last box.
    """
    deadline = time.monotonic() + max_seconds
    previous: list[str] | None = None
    stable_since = 0.0
    selected: list[str] = []
    while True:
        payload = _loads(
            await _safe(page.evaluate(READ_GROUP_TICKS_JS, list(markers or [])), "")
        )
        selected = [str(value) for value in (payload.get("selected") or [])]
        if not selected:
            return []  # nothing ticked: there is nothing to wait for
        now = time.monotonic()
        if selected != previous:
            previous, stable_since = selected, now
        elif now - stable_since >= settle_seconds:
            return selected
        if now >= deadline:
            return selected
        await asyncio.sleep(0.2)


async def remark_radio_by_name(page, field: dict, answer: str) -> bool:
    """Re-mark a radio option by its group ``name`` after a stale marker (BUG-057).

    When React re-renders the marked wrapper away, the group's native ``name``
    survives. Resolve the group by name, re-mark the option whose visible text
    matches ``answer`` with the field's own marker, and report whether one was
    found so the fill can click it through the normal path. A missing name or a
    no-match answer returns ``False`` and leaves the field to the existing error.
    """
    name = str(field.get("name") or "")
    marker = str(field.get("marker") or "")
    if not name or not marker or not str(answer or "").strip():
        return False
    payload = _loads(
        await _safe(page.evaluate(REMARK_RADIO_BY_NAME_JS, name, str(answer), marker), "")
    )
    return bool(payload.get("ok"))


async def fill_checkbox_group(
    page,
    group: list[dict],
    question: str,
    name: str,
    *,
    settings: Settings,
    answers: dict[str, str],
    ask=None,
    human: Task5Outcome | None = None,
    decide=None,
    tick=None,
) -> tuple[FormField, bool, bool, bool]:
    """Answer one checkbox group; return ``(record, known, filled, unknown)``.

    The group is answered once (never per option). A selection already ticked on
    the form is the human's own and is remembered; otherwise the LLM is asked
    (``decide``), the human is asked when that fails (``ask``), and the selected
    options are ticked through ``tick``. Anything unresolved is left *unknown* for
    Task 5 rather than guessed.
    """
    options = [g.get("option", "") for g in group if g.get("option")]
    record = FormField(
        question=question,
        field_type="checkbox",
        name=name,
        required=any(g.get("required") for g in group),
        options=options,
    )
    marker_by_option = {g.get("option", ""): g for g in group if g.get("option")}
    checked_now = [g.get("option", "") for g in group if g.get("checked") and g.get("option")]

    if checked_now:
        # Already ticked on the form: that is the human's selection. Keep it and
        # remember it, so the same question is answered automatically next time.
        record.value = ", ".join(checked_now)
        record.answered_by = "form"
        record.known = record.filled = True
        _remember_answer(settings, answers, human, question, record.value)
        return record, True, True, False

    if decide is not None:
        decision = await decide(question, "checkbox", options)
        answer = decision.answer
        record.answered_by = "llm" if decision.decided else "human"
        if decision.decided:
            record_decision(record, decision)
        selected = selected_options(answer, options)
    else:
        answer, selected = None, []

    if not selected and ask is not None:
        markers = [g.get("marker") for g in group if g.get("marker")]
        answered = await ask(
            question,
            {"type": "checkbox", "options": options, "markers": markers, "name": record.name},
        )
        if answered is not None:
            # Read the whole ticked set (the human may tick several boxes), not
            # just the one the banner's first event carried.
            ticked = await read_ticked_options(page, markers)
            value = ", ".join(ticked) if ticked else str(answered).strip()
            _remember_answer(settings, answers, human, question, value)
            answer, record.answered_by, record.rationale = value, "human", ""
            selected = selected_options(value, options)
            if not ticked:
                # The reader reports only ticks that are live on the form; when it
                # cannot see them it is because React re-rendered the marked wrapper
                # away, not because they are missing. Trust the human's ticks and
                # never re-click (that would toggle them off) (BUG-059).
                record.value, record.known, record.filled = value, True, True
                return record, True, True, False

    if selected and tick is not None:
        markers = [g.get("marker") for g in group if g.get("marker")]
        # Never toggle an option the form already holds: the human may have ticked
        # it themselves, and ``check()`` on a ``[role="checkbox"]`` wrapper would
        # untick it. Only the missing options are ticked.
        already = set(await read_ticked_options(page, markers))
        applied = 0
        for option in selected:
            if option in already:
                applied += 1
                continue
            option_field = marker_by_option.get(option)
            if option_field is None:
                continue
            ok, error = await tick(option_field)
            if ok:
                applied += 1
            elif error and not record.error:
                record.error = error
        record.value = ", ".join(selected)
        record.known = True
        record.filled = applied > 0
        return record, True, applied > 0, False

    if answer is None:
        return record, False, False, True  # nothing given: Task 5 already asked
    if len(options) <= 1 and str(answer).strip().lower() in {"no", "n", "false", "0", "off"}:
        # "No" for a single checkbox: a valid answer that leaves the box unticked.
        record.value, record.answered_by = str(answer), record.answered_by or "human"
        record.known = record.filled = True
        return record, True, True, False
    # An answer that maps to none of the options: never guess; leave it unknown.
    record.value, record.error = str(answer), "no option matched the answer"
    return record, False, False, True


__all__ = [
    "GROUP_QUESTION_JS",
    "READ_GROUP_TICKS_JS",
    "REMARK_RADIO_BY_NAME_JS",
    "fill_checkbox_group",
    "group_counts",
    "group_key",
    "read_ticked_options",
    "remark_radio_by_name",
    "selected_options",
    "selects_option",
]
