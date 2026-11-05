"""Fresh-control constraint checks and metadata for a bounded type repair."""

from src.state.type_conversion import TypeConversionAttempt
from src.tools.browser import _loads
from src.tools.linkedin_validation.type_conversion import conversion_value, numeric_field

_LIVE_CONSTRAINTS = """(value) => {
  const copy = this.cloneNode(false);
  copy.value = value;
  return JSON.stringify({fits: copy.value === value && copy.checkValidity(),
    type: this.type || this.tagName.toLowerCase(),
    inputmode: this.getAttribute('inputmode'), pattern: this.getAttribute('pattern'),
    min: this.getAttribute('min'), max: this.getAttribute('max'),
    step: this.getAttribute('step'), default_value: this.getAttribute('value'),
    maxlength: this.maxLength >= 0 ? this.maxLength : null,
    minlength: this.minLength >= 0 ? this.minLength : null});
}"""


def plan_conversion(field, source, outcome):
    audit = TypeConversionAttempt(
        question=field.get("question") or "",
        direction="text_to_number" if numeric_field(field, source) else "number_to_text",
    )
    outcome.validation.type_conversion_attempts.append(audit)
    return conversion_value(field, source), audit


def conversion_source(field, outcome):
    """Number inputs can erase an invalid string; retain the entered literal."""
    record = next(
        (
            row
            for row in reversed(outcome.fields)
            if row.question == field.get("question") and row.name == field.get("name", "")
        ),
        None,
    )
    return str(field.get("value") or (record.value if record else ""))


def has_conversion(issue, outcome):
    field = issue.get("field") or {}
    return bool(field and conversion_value(field, conversion_source(field, outcome)) is not None)


async def recheck_conversion(element, field, source, candidate):
    """The actual replacement control may have different constraints or type."""
    live = _loads(await element.evaluate(_LIVE_CONSTRAINTS, candidate))
    if not live.get("fits"):
        return None
    # Preserve inferred character-counter limits if no HTML limit is present.
    fresh = {**field, **{key: value for key, value in live.items() if value is not None}}
    return candidate if conversion_value(fresh, source) == candidate else None


def finish_conversions(validation, *, advanced=False):
    """A successful navigation accepts the repair; no extra retry is permitted."""
    for audit in validation.type_conversion_attempts:
        if audit.outcome == "entered":
            audit.outcome = (
                "accepted"
                if advanced and not validation.issues
                else "rejected"
                if validation.retry_count
                else "not_retried"
            )
