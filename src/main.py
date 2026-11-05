"""Command-line entry point for a single agent run (Tasks 1-8)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from src.configuration import load_settings, resolve_repair_model
from src.date_range import (
    DEFAULT_DATE_RANGE,
    date_range_label,
    normalize_date_range,
)
from src.date_range_choice import choose_date_range
from src.graph import graph
from src.search_query_choice import choose_search_query
from src.state import (
    DEFAULT_LOGIN_URL,
    DEFAULT_SEARCH_QUERY,
    ApplyState,
    new_state,
)
from src.submission_choice import choose_submission_mode


def _date_range_argument(value: str) -> str:
    """Validate a ``--date-range`` value and normalize its alias."""
    normalized = normalize_date_range(value)
    if not normalized:
        raise argparse.ArgumentTypeError(
            f"unknown date range {value!r}; choose past_24_hours (24h) or past_week (week)"
        )
    return normalized


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="jobagent",
        description=(
            "Log in to LinkedIn, choose Past 24 hours or Past week, search jobs, "
            "select the Easy Apply filter, open a job's Easy Apply form, pick the "
            "best-matching resume, and start filling the form (Tasks 1-4), asking "
            "the human in the browser about unknown questions and remembering the "
            "answers (Task 5). When the chosen range is exhausted the agent falls "
            "back to the other range (Task 17). Choose manual or automatic submission "
            "at startup (Task 22); after submission the agent opens the next job (Task 8)."
        ),
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_LOGIN_URL,
        help=f"LinkedIn login URL (default: {DEFAULT_LOGIN_URL})",
    )
    parser.add_argument(
        "--query",
        default=None,
        help=f"Job search query; asked when omitted (default: {DEFAULT_SEARCH_QUERY!r}).",
    )
    parser.add_argument(
        "--date-range",
        default=None,
        type=_date_range_argument,
        metavar="{24h,week}",
        help=(
            "Search Past 24 hours (24h) or Past week (week) first; the agent "
            "falls back to the other range when it is exhausted. Asked at "
            "startup when omitted."
        ),
    )
    parser.add_argument(
        "--submission-mode",
        choices=("manual", "auto"),
        default=None,
        help="Submit manually or automatically; asked at startup, default: manual.",
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
            "Close leftover JobAgent browser processes still holding the profile "
            "(e.g. after an interrupted run) and exit."
        ),
    )
    parser.add_argument(
        "--describe-new-resumes",
        action="store_true",
        help=(
            "Task 15: describe every resume in the new-resumes folder, then move each "
            "described file into the existing resumes folder (no browser)."
        ),
    )
    return parser.parse_args(argv)


def _summary(state: ApplyState) -> str:
    task1 = state.get("task1")
    task2 = state.get("task2")
    description = state.get("job_description")
    task3 = state.get("task3")
    task4 = state.get("task4")
    requested_range = state.get("date_range") or DEFAULT_DATE_RANGE
    lines = [
        "",
        f"status      : {state.get('status', 'unknown')}",
        f"url         : {state.get('url', 'unknown')}",
        f"search      : {state.get('search_query', 'unknown')!r}",
        f"submission  : {state.get('submission_mode', 'manual')}",
        f"date range  : {date_range_label(requested_range) or requested_range} "
        "(fallback: the other range)",
    ]
    if task1 is not None:
        lines += [
            f"logged in   : {task1.logged_in} (already={task1.already_logged_in})",
            f"results     : found={task1.results_found} count={task1.results_count}",
            f"ai search   : present={task1.ai_job_search_present} "
            f"clicked={task1.ai_job_search_clicked} clicks={task1.ai_job_search_clicks}",
            f"easy apply  : selected={task1.easy_apply_filter_selected}",
            f"date posted : selected={task1.date_posted_filter_selected} "
            f"value={task1.date_posted_filter_value or '(none)'}",
            f"page url    : {task1.page_url or 'unknown'}",
        ]
        if task1.screenshot_path:
            lines.append(f"screenshot  : {task1.screenshot_path}")
    if task2 is not None:
        lines += [
            f"job         : index={task2.job_index} title={task2.job_title!r} "
            f"skipped={task2.skipped_jobs} pages_visited={task2.pages_visited}",
            f"date scan   : used={task2.date_range_used or '(unknown)'} "
            f"preferred={task2.date_range_preferred or '(unknown)'} "
            f"fallback={task2.date_range_fallback_used} "
            f"week_pages={task2.pages_visited_past_week}",
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
            f"match fit   : {task3.fit or '(unknown)'}",
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
    healing = state.get("self_healing")
    if healing is not None:
        lines += [
            f"self-heal   : attempts={healing.attempts} "
            f"recovered={healing.recovered} exhausted={healing.exhausted}",
            f"self-heal bug: {', '.join(healing.bug_ids) or '(none recorded)'}",
        ]
        if healing.stop_reason:
            lines.append(f"self-heal stop: {healing.stop_reason}")
        if healing.last_bundle:
            lines.append(f"self-heal evidence: {healing.last_bundle}")
    task16 = state.get("task16")
    if task16 is not None:
        lines.append(f"resume gate : strict={task16.enabled} jobs_skipped={task16.jobs_skipped}")
        for job in task16.skipped:
            lines.append(
                f"  skipped   : {job.title!r} at {job.company!r} "
                f"(fit={job.fit or 'none'}, {job.rationale or 'no rationale'})"
            )
    task20 = state.get("task20")
    if task20 is not None:
        lines.append(f"invalid input: jobs_skipped={task20.jobs_skipped}")
        lines.extend(f"  saved link: {job.job_url} (log: {job.log_path})" for job in task20.skipped)
    task8 = state.get("task8")
    if task8 is not None:
        cap = task8.max_jobs if task8.max_jobs else "none"
        lines += [
            f"task 8      : iterations={task8.iterations} "
            f"jobs_submitted={task8.jobs_applied} cap={cap}",
            f"task 8 stop : {task8.stopped_reason or '(still running)'}",
        ]
        for job in task8.jobs:
            lines.append(
                f"  applied   : {job.title!r} at {job.company!r} "
                f"(resume={job.resume_path or 'none'}, {job.outcome})"
            )
    for entry in state.get("log", []):
        lines.append(f"  - {entry}")
    for error in state.get("errors", []):
        lines.append(f"  ! {error}")
    return "\n".join(lines)


# Task 16: with no skip cap (0), LangGraph still needs a finite step budget for
# its cycle. This is deliberately far above any realistic results list.
_UNLIMITED_SKIP_BUDGET = 1_000_000


def _recursion_limit(settings) -> int:
    """LangGraph's step budget for Task 8's loop plus Task 16's skips.

    Each submitted job costs several graph nodes, and each skipped job costs a
    ``match -> next_job`` cycle. Budget both caps so a run that matches nothing
    reaches its skip cap instead of failing on the graph recursion limit. An
    uncapped run gets a large fixed skip budget instead of zero.
    """
    cap = settings.session.max_jobs_per_run
    skip_cap = settings.session.max_skipped_jobs_per_run
    job_budget = 300 if cap == 0 else cap * 6 + 30
    skip_budget = skip_cap * 3 if skip_cap else _UNLIMITED_SKIP_BUDGET
    return job_budget + skip_budget


def _log_models(settings) -> None:
    """Print resolved general, Task 3/10, and repair models (Tasks 14/23)."""
    from src.llm_model_routing import answer_llm_settings, resume_llm_settings

    general = settings.llm.model or "(not configured)"
    resume = resume_llm_settings(settings).model or "(not configured)"
    answers = answer_llm_settings(settings).model or "(not configured)"
    repair = settings.self_healing.repair_model
    print(
        f"models      : general={general} task3={resume} task10={answers} self-healing={repair} "
        f"opencode={resolve_repair_model(repair)}"
    )


async def _run(args: argparse.Namespace) -> ApplyState:
    settings = load_settings()
    _log_models(settings)
    resumes_dir = args.resumes_dir or str(settings.resumes_dir)
    state = new_state(
        args.url,
        search_query=choose_search_query(args.query, interactive=False),
        dry_run=args.dry_run,
        resumes_dir=resumes_dir,
        date_range=args.date_range or DEFAULT_DATE_RANGE,
        submission_mode=args.submission_mode or "manual",
    )
    # Task 8's submit-and-repeat loop is a graph cycle, so raise LangGraph's
    # default recursion limit to leave room for a few nodes per job and per
    # Task 16 skip.
    return await graph.ainvoke(state, config={"recursion_limit": _recursion_limit(settings)})


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


async def _describe_new_resumes(args: argparse.Namespace) -> int:
    """Task 15: describe + move the intake resumes without launching a browser."""
    from src.tools.resume_intake import process_new_resumes  # lazy: keeps the CLI light

    settings = load_settings()
    _log_models(settings)
    resumes_dir = Path(args.resumes_dir) if args.resumes_dir else settings.resumes_dir
    new_resumes_dir = settings.new_resumes_path or (resumes_dir / "new")
    outcome = await process_new_resumes(resumes_dir, new_resumes_dir, settings)

    print(f"intake      : {outcome.intake_dir}")
    print(f"resumes     : {outcome.resumes_dir}")
    print(f"found       : {outcome.found}")
    print(f"described   : {outcome.described}")
    print(f"reused      : {outcome.reused}")
    print(f"moved       : {outcome.moved}")
    print(f"failed      : {outcome.failed}")
    for item in outcome.files:
        destination = f" -> {item.destination}" if item.destination else ""
        status = item.status or "failed"
        reused = " (reused)" if item.description_reused else ""
        print(f"  {Path(item.source).name}: {status}{reused}{destination}")
    for error in outcome.errors:
        print(f"  ! {error}")
    if not outcome.found:
        print("new resumes : none")
    return 0 if outcome.ok else 1


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
    if args.describe_new_resumes:
        try:
            return asyncio.run(_describe_new_resumes(args))
        except Exception as exc:  # noqa: BLE001 - surface a clean CLI error
            print(f"error: could not process new resumes: {exc}", file=sys.stderr)
            return 1

    # Ask what to search before asking how recent (Tasks 18/17).
    try:
        load_settings()  # Load login settings before the startup questions.
        args.query = choose_search_query(
            args.query, interactive=False if args.dry_run else None
        )
        args.date_range = choose_date_range(args.date_range)
        args.submission_mode = choose_submission_mode(args.submission_mode)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

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
