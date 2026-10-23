"""Task 5: ask the human for unknown answers, remember them, and show UI feedback.

1. Receive a form question the LLM (Task 4.1/10) could not answer from the store.
2. Show a visible browser banner saying the agent does not know the answer, pause
   the run, and read the answer the human types into (or chooses on) the form
   control itself. The answer is stored the moment it is seen (not only when the
   wait ends) and the banner confirms with a "saved" message, so nothing is lost
   to a timeout or a manual submit.
3. Remember the question -> answer mapping so Task 4.1/10 can reuse it next time.

The banner has no input: the human edits the real form control and this module
reads it. It watches only the control(s) of the question being asked, so an
unrelated edit is never mistaken for the answer. The interaction uses browser-use's
deterministic CDP actor API (``Page`` / ``Element``); no LLM is involved here.

The package is split by concern so each module stays small:
:mod:`.answer_js` (watch/read the form answer), :mod:`.banner_js` (banner DOM),
:mod:`.flow` (the pause-and-wait flow), :mod:`.store` (persisting answers). This
module re-exports the public API, so ``from src.tools.linkedin_ask_human import
...`` (and :mod:`src.tools.browser`'s lazy re-exports) keep working unchanged.
"""

from __future__ import annotations

from src.tools.linkedin_ask_human.answer_js import (
    _READ_FORM_ANSWER_JS,
    _WATCH_FORM_ANSWER_JS,
)
from src.tools.linkedin_ask_human.banner_js import (
    _DUMP_HOSTS_JS,
    _HIDE_UNKNOWN_JS,
    _MARK_SAVED_JS,
    _READ_UNKNOWN_JS,
    _SAVED_VISIBLE_SECONDS,
    _SHOW_UNKNOWN_JS,
)
from src.tools.linkedin_ask_human.flow import (
    _UNLABELED_QUESTION_RE,
    _dump_question_context,
    _finish_question,
    _looks_unlabeled,
    ask_human_for_answer,
)
from src.tools.linkedin_ask_human.store import _remember_answer, _store_answer

__all__ = [
    "_DUMP_HOSTS_JS",
    "_HIDE_UNKNOWN_JS",
    "_MARK_SAVED_JS",
    "_READ_FORM_ANSWER_JS",
    "_READ_UNKNOWN_JS",
    "_SAVED_VISIBLE_SECONDS",
    "_SHOW_UNKNOWN_JS",
    "_UNLABELED_QUESTION_RE",
    "_WATCH_FORM_ANSWER_JS",
    "_dump_question_context",
    "_finish_question",
    "_looks_unlabeled",
    "_remember_answer",
    "_store_answer",
    "ask_human_for_answer",
]
