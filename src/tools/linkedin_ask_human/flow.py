"""Task 5: show the banner, wait for the human, and remember the answer.

Split out of :mod:`src.tools.linkedin_ask_human` so each module stays small.
The run pauses here for an unknown question instead of guessing: the human
answers in the real form control, the completed answer is stored, and the
banner confirms it was saved. Unfinished values never leave the wait loop.
"""

from __future__ import annotations

import asyncio
import re
import time

from src.configuration import Settings
from src.state import Task5Outcome
from src.tools.answers import answer_echoes_question
from src.tools.browser import _append_note, _loads, _safe
from src.tools.forms import is_prompt_answer
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
from src.tools.linkedin_ask_human.completion_js import _UPDATE_PENDING_JS
from src.tools.linkedin_ask_human.store import _store_answer
from src.tools.linkedin_status_overlay import emit_step

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
            await _safe(page.evaluate(_DUMP_HOSTS_JS, list(markers or []), str(name or "")), "")
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
    options: list[str] | None = None,
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

    Only a completed answer is stored or returned, using the watcher's completion
    signal. The banner confirms the saved final value.
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
    notify(f"Task 5: I do not know {question!r}{kind}; answer it in the form field in the browser.")
    emit_step(
        notify,
        f"Waiting for you - I do not know {question!r}{kind}; answer it in the form on the page.",
    )
    await _dump_question_context(page, question, markers, name, field_type, settings, notify)
    markers_arg = list(markers or [])
    name_arg = str(name or "")
    options_arg = list(options or [])
    # The human often fills several fields at once. If the field for this question
    # already holds an answer, take it now instead of waiting for a fresh edit.
    pre = _loads(
        await _safe(
            page.evaluate(_READ_FORM_ANSWER_JS, markers_arg, name_arg, question, options_arg),
            "",
        )
    )
    pre_answer = str(pre.get("value") or "").strip()
    if pre_answer and (
        answer_echoes_question(question, pre_answer) or is_prompt_answer(pre_answer)
    ):
        pre_answer = ""  # a misread choice/aria-label is not an answer (BUG-082)
    if pre_answer and pre.get("done"):
        _store_answer(settings, question, pre_answer, human)
        await _finish_question(page, pre_answer)
        human.answered += 1
        if question not in human.answered_questions:
            human.answered_questions.append(question)
        notify(f"Task 5: picked up your answer for {question!r} from the form.")
        return pre_answer

    deadline = time.monotonic() + settings.session.ask_timeout_seconds
    activity = pre.get("activity")
    pending = pre_answer
    while True:
        payload = _loads(await _safe(page.evaluate(_READ_UNKNOWN_JS), ""))
        if str(payload.get("state") or "") == "skipped":
            await _safe(page.evaluate(_HIDE_UNKNOWN_JS))
            human.skipped += 1
            notify(f"Task 5: you skipped {question!r}; leaving it unknown.")
            return None
        answer_payload = _loads(
            await _safe(
                page.evaluate(_READ_FORM_ANSWER_JS, markers_arg, name_arg, question, options_arg),
                "",
            )
        )
        answer = str(answer_payload.get("value") or "").strip()
        if answer and (answer_echoes_question(question, answer) or is_prompt_answer(answer)):
            answer = ""  # never treat the question text as the human's answer
        if answer_payload.get("activity") != activity or answer != pending:
            activity = answer_payload.get("activity")
            pending = answer
            deadline = time.monotonic() + settings.session.ask_timeout_seconds
        await _safe(
            page.evaluate(
                _UPDATE_PENDING_JS, answer, field_type == "checkbox" and len(options_arg) > 1
            )
        )
        if answer and answer_payload.get("done"):
            _store_answer(settings, question, answer, human)
            await _finish_question(page, answer)
            human.answered += 1
            if question not in human.answered_questions:
                human.answered_questions.append(question)
            notify(f"Task 5: got an answer for {question!r} from the form.")
            return answer
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(settings.session.ask_poll_seconds)

    await _safe(page.evaluate(_HIDE_UNKNOWN_JS))
    human.timed_out += 1
    human.notes = _append_note(
        human.notes, f"timed out waiting for you to finish answering {question!r}"
    )
    notify(f"Task 5: timed out waiting for you to finish answering {question!r}.")
    return None
