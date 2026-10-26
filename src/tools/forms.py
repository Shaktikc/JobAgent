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


# Injected into the form-enumeration query (``_with_apply_root``) to read whether a
# control is required even when LinkedIn's newer SDUI layout carries no
# ``required``/``aria-required`` attribute. There the marker lives as a trailing
# ``*`` in the question label and/or an ``error-message-*`` described-by id on the
# group's fieldset (an optional control points at a ``-info`` id instead). It needs
# ``norm`` from the query's own scope, so it is injected rather than imported.
REQUIRED_MARKER_JS = r"""const requiredOf = (el, isChoice, questionText) => {
    if (el.required || el.getAttribute('aria-required') === 'true') return true;
    if (el.querySelector && el.querySelector('[required],[aria-required="true"]')) return true;
    const group = el.closest('[role="radiogroup"], [role="group"], fieldset');
    if (group) {
      if (group.getAttribute('aria-required') === 'true') return true;
      if (group.querySelector('[required],[aria-required="true"]')) return true;
      if (/(^|\s)error-message-/.test(group.getAttribute('aria-describedby') || '')) return true;
    }
    if (/(^|\s)error-message-/.test(el.getAttribute('aria-describedby') || '')) return true;
    const texts = [];
    if (questionText) texts.push(questionText);
    if (isChoice && group) {
      const legend = group.querySelector('legend');
      if (legend) texts.push(legend.innerText);
    }
    if (el.labels) Array.from(el.labels).forEach((label) => texts.push(label.innerText));
    const wrap = el.closest('label');
    if (wrap) texts.push(wrap.innerText);
    // A choice group's question label is the fieldset's own container (SDUI puts
    // it in a ``<p>`` just above the options). Only one hop, and only for a group,
    // so an unrelated '*' in a larger shared ancestor is never picked up.
    const scope = isChoice ? (group || el).parentElement : null;
    const near = scope ? scope.querySelector('legend, label, p') : null;
    if (near) texts.push(near.innerText);
    return texts.some((text) => /\*\s*$/.test(norm(text || '')));
  };"""
