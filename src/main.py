"""Command-line entry point for a single agent run (Tasks 1-5)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from src.configuration import load_settings
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
        description=(
            "Log in to LinkedIn, search jobs, select the Easy Apply filter, "
            "open a job's Easy Apply form, pick the best-matching resume, and "
            "start filling the form (Tasks 1-4), asking the human in the browser "
            "about unknown questions and remembering the answers (Task 5). The "
            "application is never submitted."
        ),
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
        "--resumes-dir",
        default=None,
        help="Folder of resumes to choose from (default: AUTOJOB_RESUMES_DIR or ./resumes)",
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
        help="Launch the browser and run the agent (requires the `browser` extra).",
    )
    parser.add_argument("--json", action="store_true", help="Print the raw final state as JSON.")
    parser.add_argument(
        "--clean-profile",
        action="store_true",
        help=(
            "Close leftover AutoJobApply browser processes still holding the profile "
            "(e.g. after an interrupted run) and exit."
        ),
    )
    return parser.parse_args(argv)


def _summary(state: ApplyState) -> str:
    task1 = state.get("task1")
    task2 = state.get("task2")
    description = state.get("job_description")
    task3 = state.get("task3")
    task4 = state.get("task4")
    lines = [
        "",
        f"status      : {state.get('status', 'unknown')}",
        f"url         : {state.get('url', 'unknown')}",
        f"search      : {state.get('search_query', 'unknown')!r}",
    ]
    if task1 is not None:
        lines += [
            f"logged in   : {task1.logged_in} (already={task1.already_logged_in})",
            f"results     : found={task1.results_found} count={task1.results_count}",
            f"ai search   : present={task1.ai_job_search_present} "
            f"clicked={task1.ai_job_search_clicked} clicks={task1.ai_job_search_clicks}",
            f"easy apply  : selected={task1.easy_apply_filter_selected}",
            f"page url    : {task1.page_url or 'unknown'}",
        ]
        if task1.screenshot_path:
            lines.append(f"screenshot  : {task1.screenshot_path}")
    if task2 is not None:
        lines += [
            f"job         : index={task2.job_index} title={task2.job_title!r} "
            f"skipped={task2.skipped_jobs} pages_visited={task2.pages_visited}",
            f"apply       : clicked={task2.easy_apply_clicked} "
            f"form_opened={task2.application_form_opened}",
        ]
        if task2.screenshot_path:
            lines.append(f"screenshot  : {task2.screenshot_path}")
    if description is not None:
        lines.append(
            f"description : title={description.title!r} company={description.company!r} "
            f"chars={len(description.body)}"
        )
    if task3 is not None:
        lines += [
            f"resumes     : dir={task3.resumes_dir} found={task3.resumes_found}",
            f"best resume : {task3.selected_path}",
            f"why         : {task3.rationale or '(none)'}",
        ]
    if task4 is not None:
        lines += [
            f"form        : open={task4.form_open} fields={task4.fields_enumerated} "
            f"known={task4.known_fields} filled={task4.filled_fields}",
            f"resume use  : {task4.resume_selection or 'none'}"
            + (f" ({task4.resume_listed_name})" if task4.resume_listed_name else ""),
            f"submitted   : {task4.submitted}",
        ]
        if task4.unknown_fields:
            lines.append(f"unknown     : {task4.unknown_fields}")
        if task4.screenshot_path:
            lines.append(f"screenshot  : {task4.screenshot_path}")
    task5 = state.get("task5")
    if task5 is not None:
        lines.append(
            f"human help  : enabled={task5.enabled} asked={task5.asked} "
            f"answered={task5.answered} skipped={task5.skipped} timed_out={task5.timed_out}"
        )
        if task5.answered_questions:
            lines.append(f"remembered  : {task5.answered_questions}")
    for entry in state.get("log", []):
        lines.append(f"  - {entry}")
    for error in state.get("errors", []):
        lines.append(f"  ! {error}")
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> ApplyState:
    resumes_dir = args.resumes_dir
    if resumes_dir is None:
        resumes_dir = str(load_settings().resumes_dir)
    state = new_state(
        args.url,
        search_query=args.query,
        dry_run=args.dry_run,
        resumes_dir=resumes_dir,
    )
    return await graph.ainvoke(state)


def _clean_profile() -> int:
    """Kill leftover browsers using the profile and clear its lock files."""
    from src.tools.browser import clean_profile  # lazy: browser-use stays optional

    settings = load_settings()
    try:
        killed = clean_profile(settings)
    except Exception as exc:  # noqa: BLE001 - surface a clean CLI error
        print(f"error: could not clean the profile: {exc}", file=sys.stderr)
        return 1
    print(f"profile     : {settings.profile_dir}")
    print(f"leftover    : closed {killed} browser process(es), cleared lock files")
    return 0


def _silence_windows_pipe_noise() -> None:
    """Suppress a harmless Windows shutdown artifact from the browser subprocess.

    On Windows, browser-use's Chrome subprocess can leave an asyncio pipe transport
    alive when the event loop closes. Its ``__del__`` then formats a
    ``ResourceWarning`` and raises "I/O operation on closed pipe", which Python
    prints as an unraisable exception *after* a successful run. Filter exactly
    that message so the CLI output stays clean; everything else is untouched.
    """
    if sys.platform != "win32":
        return
    original = sys.unraisablehook

    def hook(unraisable) -> None:  # pragma: no cover - shutdown-time only
        exc = unraisable.exc_value
        if isinstance(exc, ValueError) and "I/O operation on closed pipe" in str(exc):
            return
        original(unraisable)

    sys.unraisablehook = hook


def main(argv: list[str] | None = None) -> int:
    _silence_windows_pipe_noise()
    args = _parse_args(argv)
    if args.clean_profile:
        return _clean_profile()

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
