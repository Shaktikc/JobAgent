"""Task 5: persist a human answer (early save + remembered store entry).

Split out of :mod:`src.tools.linkedin_ask_human` so each module stays small.
"""

from __future__ import annotations

from src.configuration import Settings
from src.state import Task5Outcome
from src.tools.answers import normalize_question, save_answer
from src.tools.browser import _append_note
from src.tools.forms import is_prompt_answer


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
    if not normalize_question(question) or is_prompt_answer(answer):
        return  # a <select> prompt ("Select an option") is not an answer (BUG-037)
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
    if is_prompt_answer(answer):
        return  # never remember a select prompt as the human's answer (BUG-037)
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
