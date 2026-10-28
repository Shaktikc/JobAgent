"""Task 17's startup question: search Past 24 hours or Past week first?

The agent asks this before launching the browser unless ``--date-range`` was
supplied. The chosen range is the **primary** range; when it is exhausted the
agent falls back to the other range (24 hours ⇄ past week).

The prompt is skipped when stdin is not interactive (tests, piped output, the
LangGraph Studio server). In that case the default stays **Past 24 hours**, so
existing scripted runs keep their behaviour.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import TextIO

from src.date_range import (
    DEFAULT_DATE_RANGE,
    PAST_24_HOURS_LABEL,
    PAST_24_HOURS_VALUE,
    PAST_WEEK_LABEL,
    PAST_WEEK_VALUE,
    date_range_label,
    normalize_date_range,
)

_MENU = (
    (PAST_24_HOURS_VALUE, PAST_24_HOURS_LABEL),
    (PAST_WEEK_VALUE, PAST_WEEK_LABEL),
)
_PROMPT = "Choose 1 or 2 [1]: "


def _is_interactive() -> bool:
    """True when the process has a real terminal to ask the question on."""
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except (AttributeError, ValueError):
        return False


def choose_date_range(
    value: str | None = None,
    *,
    interactive: bool | None = None,
    input_func: Callable[[str], str] | None = None,
    stream: TextIO | None = None,
) -> str:
    """Resolve the range to scan first, asking the user when none was given.

    ``value`` is the optional ``--date-range`` argument (a normalized value or
    one of the accepted aliases such as ``24h``/``week``). An explicit invalid
    value raises :class:`ValueError`; a missing value prompts only when stdin is
    interactive, otherwise it defaults to **Past 24 hours**.
    """
    selected = normalize_date_range(value)
    if selected:
        return selected
    if (value or "").strip():
        raise ValueError(
            f"unknown date range {value!r}; choose past_24_hours (24h) "
            "or past_week (week)"
        )

    if interactive is None:
        interactive = _is_interactive()
    if not interactive:
        return DEFAULT_DATE_RANGE

    output = stream or sys.stdout
    ask = input_func or input
    print("Which jobs should I search first?", file=output)
    for index, (_, label) in enumerate(_MENU, start=1):
        other = PAST_WEEK_LABEL if index == 1 else PAST_24_HOURS_LABEL
        print(f"  {index}) {label} (fallback: {other})", file=output)

    for _ in range(3):
        try:
            answer = ask(_PROMPT)
        except (EOFError, KeyboardInterrupt):
            print(file=output)
            return DEFAULT_DATE_RANGE
        if not (answer or "").strip():
            return DEFAULT_DATE_RANGE
        selected = normalize_date_range(answer)
        if selected:
            print(f"Searching {date_range_label(selected)} first.", file=output)
            return selected
        print("Please enter 1 (Past 24 hours) or 2 (Past week).", file=output)

    print(
        f"No valid choice; searching {PAST_24_HOURS_LABEL} first.",
        file=output,
    )
    return DEFAULT_DATE_RANGE


__all__ = ["choose_date_range"]
