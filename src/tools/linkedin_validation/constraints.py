"""Conservative, fact-preserving input repairs using the live field constraints."""

import re
from decimal import Decimal, InvalidOperation
from fractions import Fraction


def _number(value: str) -> str | None:
    # Strip grouping separators only in an unambiguous thousands-group format.
    text = value.strip()
    if re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
        text = text.replace(",", "")
    return text if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text) else None


def _numeric_answer(field: dict, value: str) -> str | None:
    question = field.get("question", "").lower()
    text = value.strip()
    if "salary" in question or "compensation" in question:
        text = re.sub(r"^[$€£₹]\s*", "", text)
    direct = _number(text)
    if direct is not None:
        return direct
    # A single numeric fact with the SAME unit as the question can be expressed
    # as a number. Never convert units, choose between numbers, or infer a range.
    match = re.fullmatch(
        r"(?:I have\s+)?([\d.]+)\s+(years?|months?|days?)"
        r"(?: of experience)?[.!]?",
        text,
        re.IGNORECASE,
    )
    if match and re.search(r"\b" + match[2].rstrip("s") + r"s?\b", question):
        return _number(match[1])
    return None


def _within_constraints(field: dict, value: str, numeric: bool) -> bool:
    length = len(value.encode("utf-16-le")) // 2
    for key, passes in (("maxlength", lambda n: length <= n), ("minlength", lambda n: length >= n)):
        bound = field.get(key)
        if bound not in (None, "", -1) and not passes(int(bound)):
            return False
    pattern = field.get("pattern")
    if pattern:
        try:
            if re.fullmatch(pattern, value) is None:
                return False
        except re.error:
            return False  # An unfamiliar HTML pattern is not permission to guess.
    if numeric:
        try:
            number = Decimal(value)
            minimum = field.get("min")
            maximum = field.get("max")
            if minimum not in (None, "") and number < Decimal(str(minimum)):
                return False
            if maximum not in (None, "") and number > Decimal(str(maximum)):
                return False
            step = field.get("step") or ("1" if field.get("type") == "number" else "any")
            if step != "any":
                base = Decimal(str(minimum or field.get("default_value") or "0"))
                increment = Decimal(str(step))
                # Decimal arithmetic uses a finite context and can round away
                # fractional digits before modulo. Step checks must stay exact.
                if increment <= 0 or (Fraction(number) - Fraction(base)) % Fraction(increment):
                    return False
        except (InvalidOperation, ValueError, ZeroDivisionError, OverflowError):
            return False
    return bool(value)


def corrected_value(field: dict, answer: str) -> str | None:
    """Return a valid equivalent, or None when a safe correction is unknown."""
    text = re.sub(r"\s+", " ", str(answer or "")).strip()
    if not text:
        return None
    numeric = field.get("type") == "number" or field.get("inputmode") in {"numeric", "decimal"}
    if numeric:
        text = _numeric_answer(field, text)
        if text is None:
            return None
    return text if _within_constraints(field, text, numeric) else None


def preserves_facts(source: str, proposed: str) -> bool:
    """Require every factual component in order; only grammatical filler may go."""
    if not source.strip():
        return True  # A previously blank answer may use the grounded chooser.
    original_number, proposed_number = _number(source), _number(proposed)
    if original_number is not None and proposed_number is not None:
        return Decimal(original_number) == Decimal(proposed_number)
    original = set(re.findall(r"\w+", source.casefold()))
    candidate = set(re.findall(r"\w+", proposed.casefold()))
    if not candidate or not candidate <= original:
        return False
    # A supported subset may still omit an availability day, tool, qualification,
    # or other fact. Keep all content in the same order, including negatives and
    # qualifiers. This intentionally declines semantic rewrites we cannot prove.
    filler = {"i", "my", "a", "an", "the", "am", "have", "and"}
    original_facts = [word for word in re.findall(r"\w+", source.casefold()) if word not in filler]
    proposed_facts = [
        word for word in re.findall(r"\w+", proposed.casefold()) if word not in filler
    ]
    if original_facts != proposed_facts:
        return False
    negations = re.compile(
        r"\b(?:no|not|never|without|cannot|"
        r"(?:ca|do|does|is|are|was|were|have|has|had|would|could|should|wo)n['’]t)\b",
        re.IGNORECASE,
    )
    if bool(negations.search(source)) != bool(negations.search(proposed)):
        return False
    return sorted(re.findall(r"\d+(?:\.\d+)?", source)) == sorted(
        re.findall(r"\d+(?:\.\d+)?", proposed)
    )
