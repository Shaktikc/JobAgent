"""Resolve Task 18's free-text startup query before opening the browser."""

from __future__ import annotations

import sys
import unicodedata
from collections.abc import Callable
from typing import TextIO

from src.state import DEFAULT_SEARCH_QUERY


def _normalize(value: str) -> str:
    if any(unicodedata.category(c) == "Cc" and not c.isspace() for c in value):
        raise ValueError("Search query must not contain control characters.")
    return " ".join(value.split()) or DEFAULT_SEARCH_QUERY


def choose_search_query(
    value: str | None = None,
    *,
    interactive: bool | None = None,
    input_func: Callable[[str], str] | None = None,
    stream: TextIO | None = None,
) -> str:
    """Explicit values win; otherwise ask a terminal or use the shared default.

    Blank input selects the default. Invalid explicit values raise ValueError;
    interactive control characters allow up to three attempts.
    """
    if value is not None:
        return _normalize(value)
    if interactive is None:
        try:
            interactive = bool(sys.stdin and sys.stdin.isatty())
        except (AttributeError, ValueError):
            interactive = False
    if not interactive:
        return DEFAULT_SEARCH_QUERY

    ask = input_func or input
    output = stream or sys.stdout
    for _ in range(3):
        try:
            prompt = f"What job do you want to search for? [{DEFAULT_SEARCH_QUERY}]: "
            return _normalize(ask(prompt))
        except (EOFError, KeyboardInterrupt):
            print(file=output)
            return DEFAULT_SEARCH_QUERY
        except ValueError as exc:
            print(str(exc), file=output)
    print(f"No valid query; searching {DEFAULT_SEARCH_QUERY!r}.", file=output)
    return DEFAULT_SEARCH_QUERY
