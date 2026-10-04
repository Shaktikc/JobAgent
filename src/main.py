"""Command-line entry point for a single Task 1 run."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from src.graph import graph
from src.state import (
    DEFAULT_LOGIN_URL,
    DEFAULT_SEARCH_QUERY,
    ApplyState,
    new_state,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="autojob",
        description="Log in to LinkedIn, search jobs, and select Easy Apply (Task 1).",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_LOGIN_URL,
        help=f"LinkedIn login URL (default: {DEFAULT_LOGIN_URL})",
    )
    parser.add_argument(
        "--query",
        default=DEFAULT_SEARCH_QUERY,
        help=f"Job search query (default: {DEFAULT_SEARCH_QUERY!r})",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Validate the run without launching a browser (default).",
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Launch the browser and run Task 1 (requires the `browser` extra).",
    )
    parser.add_argument("--json", action="store_true", help="Print the raw final state as JSON.")
    return parser.parse_args(argv)


def _summary(state: ApplyState) -> str:
    outcome = state.get("outcome")
    lines = [
        "",
        f"status      : {state.get('status', 'unknown')}",
        f"url         : {state.get('url', 'unknown')}",
        f"search      : {state.get('search_query', 'unknown')!r}",
    ]
    if outcome is not None:
        lines += [
            f"logged in   : {outcome.logged_in} (already={outcome.already_logged_in})",
            f"results     : found={outcome.results_found} count={outcome.results_count}",
            f"easy apply  : selected={outcome.easy_apply_filter_selected}",
            f"page url    : {outcome.page_url or 'unknown'}",
        ]
        if outcome.screenshot_path:
            lines.append(f"screenshot  : {outcome.screenshot_path}")
    for entry in state.get("log", []):
        lines.append(f"  - {entry}")
    for error in state.get("errors", []):
        lines.append(f"  ! {error}")
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> ApplyState:
    state = new_state(args.url, search_query=args.query, dry_run=args.dry_run)
    return await graph.ainvoke(state)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        state = asyncio.run(_run(args))
    except Exception as exc:  # noqa: BLE001 - surface a clean CLI error
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        printable = {
            k: (v.model_dump() if hasattr(v, "model_dump") else v) for k, v in state.items()
        }
        print(json.dumps(printable, indent=2, default=str))
    else:
        print(_summary(state))

    return 0 if state.get("status") == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
