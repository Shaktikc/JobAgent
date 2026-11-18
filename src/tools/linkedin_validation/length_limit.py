"""Conservative prefix shortening of rejected required free text."""

import re

from src.tools.linkedin_validation.constraints import _number, _within_constraints
from src.tools.linkedin_validation.type_conversion import numeric_field


def units(value):
    return len(value.encode("utf-16-le")) // 2


def shortening_value(field, source):
    if not field.get("required") or field.get("kind", "input") not in {"input", "textarea"}:
        return None
    if field.get("type", "text") not in {"text", "textarea", "search", "input"}:
        return None
    limit = field.get("maxlength")
    if limit in (None, "") or int(limit) <= 0 or units(source) <= int(limit):
        return None
    if numeric_field(field, source) or _number(source) is not None:
        return None
    if re.search(r"\b(?:no|not|never|without|cannot|neither|nor)\b|n['\u2019]t\b", source, re.I):
        return None
    text = re.sub(r"\s+", " ", source).strip()
    candidates = [text]
    boundaries = [
        match.start()
        for match in re.finditer(" ", text)
        if units(text[: match.start()]) <= int(limit)
    ]
    if boundaries:
        candidates += [text[:end] for end in reversed(boundaries)]
    elif not re.search(r"[\d@:/_.-]", text.split(" ")[0]):
        candidates += [text[:end] for end in range(len(text) - 1, 0, -1)]
    for candidate in candidates:
        candidate = candidate.rstrip(" ,;:.!?")
        while re.search(r"\b(and|or|but|with|for|to|of|in|on|at|by|from)$", candidate, re.I):
            candidate = candidate.rsplit(" ", 1)[0] if " " in candidate else ""
            candidate = candidate.rstrip(" ,;:.!?")
        if re.search(r"\d", text[len(candidate) :]):
            continue
        if candidate and _within_constraints(field, candidate, False):
            return candidate
    return None
