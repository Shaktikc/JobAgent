"""Task 19: experience-neutral view for resume matching.

The employer's years-of-experience figure is advisory, not a gate: a candidate
with fewer years than requested is still allowed to be rated `strong`. This
module builds the view of the job and of each resume profile that the matcher
is allowed to judge, so a numeric years shortfall cannot lower a rating.

The original job description and the stored resume profiles are never modified;
only the match input is neutralised.
"""

from __future__ import annotations

import re

from .models import ResumeDescription

_NUMBER = (
    r"(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)"
)
_RANGE = (
    rf"{_NUMBER}(?:\s*(?:[-–—]|to)\s*{_NUMBER}\+?|\+|\s+plus)?"
)
_FILLER = r"(?:relevant\s+|professional\s+|industry\s+|work\s+)*"

# Order matters: consume a full "years of experience" requirement first, then
# the "experience required: N years" form, then any leftover numeric years
# phrase. The last pattern is deliberately broad: a years figure in company
# history is also removed from the *match view* only.
_PATTERNS = (
    (
        re.compile(
            rf"(?i)\b(?:at\s+least|minimum(?:\s+of)?|min\.?)\s+"
            rf"{_RANGE}\s*(?:years?|yrs?\.?)['?]?\s*(?:of\s+)?{_FILLER}experience\b"
        ),
        "experience",
    ),
    (
        re.compile(
            rf"(?i)\b{_RANGE}\s*(?:years?|yrs?\.?)['?]?\s*(?:of\s+)?"
            rf"{_FILLER}experience\b"
        ),
        "experience",
    ),
    (
        re.compile(
            rf"(?i)\bexperience\s*(?:required|preferred)?\s*[:\-]?\s*"
            rf"{_NUMBER}\s*(?:years?|yrs?\.?)"
        ),
        "experience",
    ),
    (
        re.compile(
            rf"(?i)\b(?:at\s+least|minimum(?:\s+of)?|min\.?)\s+"
            rf"{_NUMBER}\s*(?:years?|yrs?\.?)"
        ),
        "",
    ),
    (
        re.compile(rf"(?i)\b{_RANGE}\s*(?:years?|yrs?\.?)['?]?"),
        "",
    ),
)


def neutralize_experience_requirements(text: str) -> str:
    """Return ``text`` without numeric years-of-experience requirements.

    Everything else is preserved. Text with no numeric years phrase is returned
    unchanged (including its original whitespace), which keeps matches stable.
    """
    raw = text or ""
    updated = raw
    for pattern, replacement in _PATTERNS:
        updated = pattern.sub(replacement, updated)
    if updated == raw:
        return text
    updated = re.sub(r"[ \t]{2,}", " ", updated)
    updated = re.sub(r"[ \t]+([,.;:!?])", r"\1", updated)
    return updated.strip()


def profile_for_match(description: ResumeDescription) -> dict:
    """The resume profile as sent to the matcher, without `years_experience`.

    Years of experience remain in the stored profile for Task 12; they are not
    part of the evidence the matcher is allowed to judge.
    """
    payload = description.model_dump()
    payload.pop("years_experience", None)
    return payload


__all__ = [
    "neutralize_experience_requirements",
    "profile_for_match",
]
