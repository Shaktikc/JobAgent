"""Pure helpers for Easy Apply form handling, plus one injected DOM-query fragment.

These cover resume-name matching (so a resume already listed on the form is
selected instead of uploaded again) and button classification (so the agent can
advance a multi-step form but never click **Submit application**).

``REQUIRED_MARKER_JS`` is the one piece of browser-side code here: it is injected
into the enumeration query (see ``form_queries.scripts``). It lives in this module
because the self-healing loop reloads ``src.tools.forms`` before
``form_queries.scripts``, so the injected helper is always the reloaded one.
"""

from __future__ import annotations

import re
from pathlib import Path

# Phrases that mean "finish the application" — never clicked by the agent.
_SUBMIT_HINTS = (
    "submit application",
    "submit your application",
    "submit",
)

# Phrases on buttons that advance to the next step of a multi-step form.
_NEXT_HINTS = (
    "next",
    "continue",
    "review",
    "save and continue",
    "save & continue",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def normalize_resume_name(value: str) -> str:
    """Reduce a resume file name or path to a comparable key.

    ``ShaktiKC_Resume_python_Node_Senior.pdf`` and ``ShaktiKC Resume python Node
    Senior`` both become ``shaktikcresumepythonnodesenior``.
    """
    stem = Path(value).stem if value else ""
    return re.sub(r"[^a-z0-9]", "", stem.lower())


def pick_listed_resume(chosen: str, listed_names: list[str]) -> str | None:
    """Return the listed resume name matching ``chosen`` (or ``None``).

    Matching is by normalized name; a containment fallback tolerates suffixes
    such as ``(1)`` or a trailing "Selected" label.
    """
    wanted = normalize_resume_name(chosen)
    if not wanted:
        return None
    for name in listed_names:
        if normalize_resume_name(name) == wanted:
            return name
    for name in listed_names:
        candidate = normalize_resume_name(name)
        if candidate and (candidate in wanted or wanted in candidate):
            return name
    return None


def looks_like_submit(text: str) -> bool:
    """True when a button would submit the application."""
    return any(hint in _normalize(text) for hint in _SUBMIT_HINTS)


def looks_like_next(text: str) -> bool:
    """True when a button advances a multi-step form (never a submit button)."""
    normalized = _normalize(text)
    if looks_like_submit(normalized):
        return False
    return any(hint in normalized for hint in _NEXT_HINTS)


def answers_match(option: str, answer: str) -> bool:
    """True when a radio/checkbox option label corresponds to ``answer``."""
    left = _normalize(option)
    right = _normalize(answer)
    if not left or not right:
        return False
    return left == right or left.startswith(right) or right in left


# A <select> option value that means "no choice made yet". LinkedIn uses ``""``
# for its disabled "Select an option" prompt; older forms use a sentinel value.
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

# Prompt *texts* (rather than values) that a <select> shows before a real choice.
# "None" is deliberately absent: it is a legitimate answer for many questions.
_SELECT_PROMPT_TEXTS = {
    "select",
    "select...",
    "select an option",
    "select option",
    "select one",
    "choose",
    "choose an option",
    "choose one",
    "please select",
    "please choose",
    "pick an option",
}


def select_is_answered(value: str, selected_text: str = "") -> bool:
    """True when a ``<select>`` holds a real answer, not its prompt option.

    BUG-037: the prompt option ("Select an option") was read and stored as the
    human's answer. The prompt can carry ``value=""`` (LinkedIn) or a sentinel
    value (older forms) with prompt text, so both are checked.
    """
    text = _normalize(selected_text)
    if text in _SELECT_PROMPT_TEXTS:
        return False
    normalized = _normalize(value)
    return bool(normalized) and normalized not in _SELECT_PLACEHOLDERS


def is_prompt_answer(answer: str) -> bool:
    """True when ``answer`` is really a select prompt, never a real answer.

    A safety net for the store: even if a layout slips past the reader, a prompt
    must never be remembered as the human's answer (BUG-037).
    """
    text = _normalize(answer).strip(".:*").strip()
    return text in _SELECT_PROMPT_TEXTS


_RESUME_FILENAME_RE = re.compile(r"\.(pdf|docx|txt|md)\b", re.IGNORECASE)


def looks_like_resume_field(question: str, options: list[str] | None = None) -> bool:
    """True for the resume-selection control (handled apart from normal fields)."""
    normalized = _normalize(question)
    if "resume" in normalized:
        return True
    return any(_RESUME_FILENAME_RE.search(option or "") for option in (options or []))


def pick_next_button(buttons: list[dict]) -> dict | None:
    """Return the first non-submit button that advances the form, if any."""
    for button in buttons:
        text = button.get("text", "")
        if looks_like_next(text) and not button.get("disabled"):
            return button
    return None


# The enumeration query passes only this question's own visible label. Metadata,
# error-message IDs and option/ancestor markers never override an unstarred label.
REQUIRED_MARKER_JS = r"""const requiredOf = (el, isChoice, questionText) => {
    return (questionText || '').includes('*');
  };"""


# Injected into the form-enumeration query to derive a stable step identity. It
# hides transient live-region/typeahead text before hashing the modal's content: a
# city suggestion list opening or closing must not look like a new step, or a
# Next click that did not advance is mistaken for progress (BUG-056). It shares
# the query's ``norm`` helper.
STEP_IDENTITY_JS = r"""const stepIdentity = (modal) => {
    const transient = Array.from(modal.querySelectorAll(
      '[role="status"], [aria-live], [role="listbox"], [role="option"], '
      + '[data-testid*="typeahead-result"], [data-testid*="typeahead-list"], '
      + '[role="alert"], .artdeco-inline-feedback, [data-testid*="helper-text"], '
      + '[id*="error"], [data-test-form-element-error-messages]'
    ));
    // Rejection feedback and character counters change on the SAME step. They
    // must not make a rejected Next click appear to have advanced (Task 20).
    modal.querySelectorAll('p,span').forEach((el) => {
      if (/^(?:invalid input[.!]?|\d+\s*\/\s*\d+)$/i.test(norm(el.innerText))) transient.push(el);
    });
    const saved = transient.map((el) => el.style.display);
    transient.forEach((el) => { el.style.display = 'none'; });
    const text = norm(modal.innerText);
    transient.forEach((el, index) => { el.style.display = saved[index]; });
    const progressMatch = text.match(
      /\b\d+\s*(?:\/|of)\s*\d+\s*(?:pages?|steps?)\b/i
    );
    const progress = progressMatch ? progressMatch[0] : '';
    const headings = Array.from(modal.querySelectorAll('h1, h2, h3, h4'))
      .filter((h) => h.getClientRects().length)
      .map((h) => norm(h.innerText)).filter(Boolean).join(' | ');
    let hash = 0;
    // Controls/questions already distinguish fillable steps in _form_signature.
    // Hash only fieldless review content: arbitrary server errors on a fillable
    // step must never masquerade as a successful navigation.
    const hasControls = Array.from(modal.querySelectorAll('input,textarea,select,'
      + '[role="radio"],[role="checkbox"]')).some((el) => el.getClientRects().length);
    const stableText = hasControls ? '' : text;
    for (let i = 0; i < stableText.length; i++) {
      hash = (hash * 31 + stableText.charCodeAt(i)) | 0;
    }
    return [progress, headings, 'text:' + (hash >>> 0)].filter(Boolean).join(' \u00b7 ');
  };"""


# Commit a value typed into a LinkedIn typeahead (its city/location control is a
# combobox, not a plain text input). Setting the input's value alone leaves the
# field uncommitted, so Next stays on the step and the suggestion list toggles the
# modal text (BUG-056). This clicks the suggestion matching the value once the
# list renders, and blurs the field so the following Next click is not swallowed.
TYPEAHEAD_COMMIT_JS = r"""
(value) => {
  const autocomplete = (this.getAttribute('aria-autocomplete') || '').toLowerCase();
  const role = (this.getAttribute('role') || '').toLowerCase();
  const testid = (this.getAttribute('data-testid') || '').toLowerCase();
  const isTypeahead = autocomplete === 'list' || role === 'combobox'
    || testid.includes('typeahead');
  if (!isTypeahead) return '';
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const wanted = norm(value);
  const first = wanted.split(/[,/(]/)[0].trim();
  const pick = () => {
    const ids = (this.getAttribute('aria-owns') || '').split(/\s+/).filter(Boolean);
    let options = [];
    ids.forEach((id) => {
      const list = document.getElementById(id);
      if (list) options.push(...list.querySelectorAll('[role="option"], li'));
    });
    if (!options.length) {
      options = Array.from(document.querySelectorAll('[role="option"]'))
        .filter((option) => option.getClientRects().length);
    }
    const scored = options.map((option) => {
      const text = norm(option.innerText);
      let score = -1;
      if (text && text === wanted) score = 3;
      else if (text && wanted && (text.includes(wanted) || wanted.includes(text))) score = 2;
      else if (first && text && text.split(/[,/(]/)[0].trim() === first) score = 1;
      return { option: option, score: score };
    }).filter((item) => item.score > 0);
    if (!scored.length) return false;
    scored.sort((a, b) => b.score - a.score);
    const option = scored[0].option;
    ['mousedown', 'mouseup', 'click'].forEach((type) =>
      option.dispatchEvent(new MouseEvent(type, {
        bubbles: true, cancelable: true, view: window
      }))
    );
    setTimeout(() => { if (this.blur) this.blur(); }, 0);
    return true;
  };
  if (pick()) return 'clicked';
  // Suggestions can render after the input/change event; watch briefly for them.
  const observer = new MutationObserver(() => {
    if (pick()) observer.disconnect();
  });
  observer.observe(document.body, { childList: true, subtree: true });
  setTimeout(() => observer.disconnect(), 3000);
  return 'watching';
}
"""
