"""Secret/PII redaction and bounded clipping for crash bundles (Task 33)."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[redacted]"
MAX_STRING = 2_000
MAX_LIST = 200
MAX_DEPTH = 12

_SENSITIVE_KEY_PARTS = (
    "password", "passwd", "secret", "token", "cookie", "authorization",
    "session_id", "sessionid", "credential",
)
_SENSITIVE_QUESTION = re.compile(
    r"password|passcode|\bssn\b|social security|bank account|routing number"
    r"|account number|credit card|card number|\bcvv\b|\bcvc\b",
    re.IGNORECASE,
)
_ANSWER_KEYS = ("value", "answer", "selected", "current_value", "filled_value", "text_value")
_QUESTION_KEYS = ("label", "question", "name", "aria_label", "placeholder")

# Obvious credential shapes inside free text (tracebacks, log lines, URLs).
_CREDENTIAL = re.compile(
    r"\bsk-[A-Za-z0-9_-]{8,}"
    r"|\bBearer\s+[A-Za-z0-9._~+/=-]+"
    r"|\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret"
    r"|li_at|jsessionid|cookie|authorization)\s*[:=]\s*(?:(?:Bearer|Basic|Token)\s+)?"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)",
    re.IGNORECASE,
)


def is_sensitive_key(key: Any) -> bool:
    """True for keys whose string values must never be written out."""
    name = str(key).lower()
    if any(part in name for part in _SENSITIVE_KEY_PARTS):
        return True
    return "key" in name and "keyword" not in name


def scrub_text(text: str) -> str:
    """Replace credential-shaped substrings with ``[redacted]``."""
    return _CREDENTIAL.sub(REDACTED, text) if text else text


class Clipper:
    """Redact and clip a value into a JSON-safe structure, noting truncation."""

    def __init__(self, max_string: int = MAX_STRING, max_list: int = MAX_LIST) -> None:
        self.max_string = max_string
        self.max_list = max_list
        self.notes: list[str] = []

    def note(self, message: str) -> None:
        if message not in self.notes and len(self.notes) < 50:
            self.notes.append(message)

    def text(self, value: str, where: str = "", limit: int | None = None) -> str:
        limit = limit or self.max_string
        value = scrub_text(value)
        if len(value) > limit:
            self.note(f"{where or 'a string'} clipped from {len(value)} to {limit} chars")
            return value[:limit] + "…[clipped]"
        return value

    def clean(self, value: Any, where: str = "", depth: int = 0) -> Any:
        if depth > MAX_DEPTH:
            self.note(f"{where or 'value'} nested deeper than {MAX_DEPTH} levels")
            return "[too deep]"
        if hasattr(value, "model_dump"):
            try:
                value = value.model_dump(mode="json")
            except Exception:  # noqa: BLE001
                value = repr(value)
        if value is None or isinstance(value, bool | int | float):
            return value
        if isinstance(value, str):
            return self.text(value, where)
        if isinstance(value, dict):
            return self._mapping(value, where, depth)
        if isinstance(value, list | tuple | set | frozenset):
            items = list(value)
            if len(items) > self.max_list:
                self.note(f"{where or 'a list'} clipped from {len(items)} to {self.max_list} items")
                items = items[: self.max_list]
            return [self.clean(item, f"{where}[]", depth + 1) for item in items]
        return self.text(repr(value), where)

    def _mapping(self, value: dict, where: str, depth: int) -> dict:
        question = " ".join(str(value.get(key) or "") for key in _QUESTION_KEYS)
        sensitive_form = bool(question.strip()) and bool(_SENSITIVE_QUESTION.search(question))
        result: dict = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= self.max_list:
                self.note(f"{where or 'a mapping'} clipped to {self.max_list} keys")
                break
            name = str(key)
            path = f"{where}.{name}" if where else name
            if isinstance(item, str) and item and is_sensitive_key(name):
                result[name] = REDACTED
            elif sensitive_form and name in _ANSWER_KEYS and item not in (None, "", [], {}):
                result[name] = REDACTED
            else:
                result[name] = self.clean(item, path, depth + 1)
        return result


def redact(value: Any, clipper: Clipper | None = None, where: str = "") -> Any:
    """Convenience wrapper: redact/clip ``value`` with a fresh or shared clipper."""
    return (clipper or Clipper()).clean(value, where)


__all__ = ["REDACTED", "Clipper", "is_sensitive_key", "redact", "scrub_text"]
