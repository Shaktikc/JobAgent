"""Task 22: resolve the run's explicit automatic/manual submission choice."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import TextIO


def choose_submission_mode(
    value: str | None = None,
    *,
    interactive: bool | None = None,
    input_func: Callable[[str], str] | None = None,
    stream: TextIO | None = None,
) -> str:
    """Ask before running; missing input always defaults to manual submission."""
    if value is not None:
        if value not in {"manual", "auto"}:
            raise ValueError("submission mode must be manual or auto")
        return value
    if interactive is None:
        try:
            interactive = bool(sys.stdin and sys.stdin.isatty())
        except (AttributeError, ValueError):
            interactive = False
    if not interactive:
        return "manual"

    output = stream or sys.stdout
    ask = input_func or input
    print("Should I submit applications automatically, or will you submit manually?", file=output)
    print("  1) Manual - leave each application ready for you to review and submit (default)",
          file=output)
    print("  2) Automatic - submit completed applications for this run", file=output)
    for _ in range(3):
        try:
            answer = ask("Choose 1 or 2 [1]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(file=output)
            return "manual"
        if answer in {"", "1", "manual"}:
            return "manual"
        if answer in {"2", "auto", "automatic"}:
            return "auto"
        print("Choose 1 (manual) or 2 (automatic).", file=output)
    print("No valid choice received; using manual submission.", file=output)
    return "manual"
