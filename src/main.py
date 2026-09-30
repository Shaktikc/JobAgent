"""Entry point for AutoJobApply: graph execution entry point and command dispatch.

Command surface, wired task by task:

- ``login``  -> Task 3/17 (browser-use session, manual login)
- ``run``    -> Task 8/17 (minimal: ``--url ... --dry-run``), completed in Task 15
- ``search`` -> Task 12 (discovery)
- ``status`` -> Task 15 (orchestration)
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from src.configuration import AppSettings

EXIT_NOT_IMPLEMENTED = 2
EXIT_FAILED = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autojobapply",
        description=(
            "LinkedIn Easy Apply agent. Searches jobs, fills applications from your "
            "resumes, and pauses for human review before every submission."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser(
        "login",
        help="Open the browser and log in to LinkedIn manually; the session is persisted.",
    )

    run = subcommands.add_parser("run", help="Search, fill, review, and apply.")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Fill and review but NEVER submit. Default during early validation.",
    )
    run.add_argument(
        "--url",
        metavar="JOB_URL",
        default=None,
        help="Process a single job URL instead of running a search.",
    )

    subcommands.add_parser("search", help="Populate the database with matching jobs; fill nothing.")

    subcommands.add_parser("status", help="Show recorded application state.")

    return parser


async def _run_url(settings: AppSettings, job_url: str, *, dry_run: bool) -> int:
    """Run the single-job pipeline (Task 8/17)."""
    from src.configuration import FactsConfig
    from src.graph import Runtime, resolve_default_resume, run_single_url
    from src.nodes.discover import DiscoveryError, NotEasyApplyError
    from src.nodes.fill import FillError
    from src.tools import browser, store
    from src.tools.browser_agent import build_openrouter_llm
    from src.tools.guard import Guard, GuardHalt

    if not settings.llm.model:
        print(
            "Set AUTOJOB_LLM_MODEL (and OPENROUTER_API_KEY) before running; "
            "browser-use needs a model. See Task 9.",
            file=sys.stderr,
        )
        return EXIT_FAILED

    conn = store.connect(settings.paths.db)
    store.init_db(conn)
    guard = Guard(settings.guard, settings.paths, conn)

    try:
        guard.assert_startable()
        guard.assert_can_apply()
    except GuardHalt as halt:
        print(str(halt), file=sys.stderr)
        return EXIT_FAILED

    facts = FactsConfig.from_yaml(settings.paths.config / "facts.yaml")
    resume = resolve_default_resume(settings)

    try:
        async with browser.browser_session(settings) as session:
            runtime = Runtime(
                settings=settings,
                conn=conn,
                browser=session,
                llm=build_openrouter_llm(settings.llm.model),
                guard=guard,
                facts=facts,
                resume_path=resume,
                dry_run=dry_run,
                job_url=job_url,
            )
            final = await run_single_url(runtime)
    except NotEasyApplyError as exc:
        print(f"Skipping job: {exc}", file=sys.stderr)
        return EXIT_FAILED
    except DiscoveryError as exc:
        print(f"Could not read job: {exc}", file=sys.stderr)
        return EXIT_FAILED
    except GuardHalt as halt:
        print(str(halt), file=sys.stderr)
        return EXIT_FAILED
    except FillError as exc:
        print(f"Filling failed: {exc}", file=sys.stderr)
        return EXIT_FAILED

    print(
        f"Done. status={final.get('status')} "
        f"submitted={final.get('submitted')} "
        f"confirmation={final.get('confirmation')}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Load settings early so a broken environment fails before any browser work.
    settings = AppSettings.from_env()
    settings.paths.ensure_runtime_dirs()

    if args.command == "login":
        # Imported lazily so `--help` and non-browser commands stay lightweight.
        from src.tools.browser import login

        return asyncio.run(login(settings))

    if args.command == "run":
        if not args.url:
            print(
                "`run` requires --url until search is implemented in Task 12.",
                file=sys.stderr,
            )
            return EXIT_NOT_IMPLEMENTED
        return asyncio.run(_run_url(settings, args.url, dry_run=args.dry_run))

    print(
        f"[scaffold] '{args.command}' is not implemented yet; see SPEC.md and tasks/todo.md.",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


if __name__ == "__main__":
    raise SystemExit(main())
