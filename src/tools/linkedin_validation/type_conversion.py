"""Restate a rejected answer's single numeric fact without inventing context."""

import re

from src.tools.linkedin_validation.constraints import _number, _within_constraints

_UNITS = re.compile(r"\b(years?|months?|weeks?|days?|hours?|minutes?|seconds?)\b", re.I)
_FACT = re.compile(
    r"(?:I have\s+)?~?\s*([+-]?\d+(?:\.\d+)?)\+?"
    r"(?:\s+([a-z]+)(?: of experience)?)?[.!]?",
    re.I,
)


def _unit(question: str) -> str | None:
    units = {match[0].lower().rstrip("s") for match in _UNITS.finditer(question)}
    if len(units) == 1:
        return units.pop() + "s"
    if units:
        return None
    count = re.search(r"\b(?:how many|number of|count of)\s+([a-z]+s)\b", question, re.I)
    return count[1].lower() if count else None


def numeric_field(field: dict, source: str = "") -> bool:
    """Recognise numeric controls, including text controls with numeric metadata."""
    if field.get("type") == "number" or field.get("inputmode") in {"numeric", "decimal"}:
        return True
    if any(field.get(key) not in (None, "") for key in ("min", "max")):
        return True
    pattern = field.get("pattern") or ""
    # Accept only numeric regex syntax; a pattern admitting arbitrary text is
    # not evidence that stripping context would help.
    tokens = r"(?:\\d|\\[.\-+]|\[0-9\]|\[[.\-+]+\]|[0-9^$()?+*{}|,:\-])+"
    if re.search(r"\\d|\[0-9\]", pattern) and re.fullmatch(tokens, pattern):
        return True
    # LinkedIn's SDUI can enforce a numeric answer server-side while exposing
    # only type=text and generic "Invalid input". A quantified question and a
    # rejected single fact still permit the same conservative numeric restatement.
    return bool(
        _unit(field.get("question") or "") and _FACT.fullmatch(source) and _number(source) is None
    )


def conversion_value(field: dict, answer: str) -> str | None:
    """Return an equivalent number/text value only for a rejected free input.

    This helper is called only after visible validation, never during ordinary
    answer lookup. Unsupported wording is deliberately left to Task 20.
    """
    if field.get("kind", "input") not in {"input", "textarea"}:
        return None
    if field.get("type", "text") not in {"input", "text", "number", "textarea", "search"}:
        return None
    source = str(answer).strip()
    question = field.get("question") or ""
    numeric = numeric_field(field, source)
    if numeric:
        match = _FACT.fullmatch(source)
        if not match or _number(source) is not None:
            return None
        if match[2] and match[2].lower().rstrip("s") != (_unit(question) or "").rstrip("s"):
            return None
        value = match[1].lstrip("+")
    else:
        unit = _unit(question)
        if not unit or not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", source):
            return None
        value = f"{source} {unit}"
    try:
        return value if _within_constraints(field, value, numeric) else None
    except (TypeError, ValueError, OverflowError):
        return None
