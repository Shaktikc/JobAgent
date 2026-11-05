"""Task 5: persist completed human answers and update the in-memory store.

Split out of :mod:`src.tools.linkedin_ask_human` so each module stays small.
"""

from __future__ import annotations

from src.configuration import Settings
from src.state import Task5Outcome
from src.tools.answers import answer_echoes_question, load_answers, normalize_question, save_answer
from src.tools.browser import _append_note
from src.tools.forms import is_prompt_answer


def _store_answer(
    settings: Settings,
    question: str,
    answer: str,
    human: Task5Outcome | None,
) -> None:
    """Persist a completed answer; the wait loop enforces completion before calling.

    The fill caller also updates its in-memory mapping through `_remember_answer`.
    Write failures are reported in the human outcome without crashing the wait.
    """
    if (
        not normalize_question(question)
        or is_prompt_answer(answer)
        or answer_echoes_question(question, answer)
    ):
        # A <select> prompt ("Select an option") is not an answer (BUG-037), and
        # the question text itself is never an answer (BUG-082).
        return
    try:
        save_answer(settings.answers_file, question, answer)
    except OSError as exc:  # noqa: BLE001 - a failed write must not stop the wait
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
    if is_prompt_answer(answer) or answer_echoes_question(question, answer):
        # Never remember a select prompt (BUG-037) or the question itself
        # (BUG-082) as the human's answer.
        return
    key = normalize_question(question)
    previous = answers.get(key)
    answers[key] = answer
    try:
        if load_answers(settings.answers_file).get(key) != answer:
            save_answer(settings.answers_file, question, answer)
    except OSError as exc:  # noqa: BLE001 - a failed write must not stop the fill
        if human is not None:
            human.notes = _append_note(human.notes, f"could not save {question!r}: {exc}")
        return
    if human is not None:
        action = "updated the stored answer" if previous and previous != answer else "remembered"
        human.notes = _append_note(human.notes, f"{action} the answer for {question!r}")
