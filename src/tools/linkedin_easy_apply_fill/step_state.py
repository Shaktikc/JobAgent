"""Stable step identity and honest notes for unanswered required questions."""

from src.state import FormField


def _form_signature(title: str, fields: list[dict], step: str = "") -> str:
    """Include headings/progress so consecutive fieldless review steps differ."""
    parts = [title or "", step or ""]
    for field in fields:
        parts.append(
            "|".join(str(field.get(key, "")) for key in ("kind", "question", "name", "option"))
        )
    return "\n".join(parts)


def _blocking_questions(records: list[FormField]) -> list[str]:
    """A known answer still blocks navigation when its fill action failed."""
    blocking: list[str] = []
    for record in records:
        if not record.required or (record.known and record.filled):
            continue
        question = record.question or record.name
        if record.error:
            question = f"{question} ({record.error})"
        if question and question not in blocking:
            blocking.append(question)
    return blocking


def _blocked_note(prefix: str, blocking: list[str]) -> str:
    if blocking:
        return (
            f"{prefix}; required questions are unanswered: "
            + ", ".join(blocking)
            + " - stopping before Submit"
        )
    return f"{prefix}; stopping before Submit"
