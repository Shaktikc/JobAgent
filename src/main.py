"""Entry point for AutoJobApply: graph execution entry point and command dispatch.

Scaffold state: the command surface is frozen so `--help` works and downstream
tasks have a stable CLI, but each command is wired to its node in a later task:

- ``login``  -> Task 3 (session)
- ``run``    -> Task 8 (minimal: ``--url ... --dry-run``), completed in Task 15
- ``search`` -> Task 12 (discovery)
- ``status`` -> Task 15 (orchestration)
"""

from __future__ import annotations

import argparse
import sys

from src.configuration import AppSettings

EXIT_NOT_IMPLEMENTED = 2


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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Load settings early so a broken environment fails before any browser work.
    settings = AppSettings.from_env()
    settings.paths.ensure_runtime_dirs()

    if args.command == "login":
        # Imported lazily so `--help` and non-browser commands stay lightweight.
        from src.tools.browser import login

        return login(settings)

    print(
        f"[scaffold] '{args.command}' is not implemented yet; see SPEC.md and tasks/todo.md.",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


if __name__ == "__main__":
    raise SystemExit(main())
