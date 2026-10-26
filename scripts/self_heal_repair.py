"""Task 11: hand a failure bundle to the OpenCode agent so it repairs the code.

The self-healing loop runs ``AUTOJOB_SELF_HEAL_REPAIR_COMMAND`` after it closes the
failed browser (see :mod:`src.tools.self_healing.recovery`). This wrapper is that
command: it reads the evidence bundle from the environment, builds a repair prompt
that follows ``AGENTS.md`` (self-healing loop + bug-log + file-size rules) **and the
``incremental-implementation`` skill**, and runs the OpenCode CLI non-interactively in
the project root::

    opencode run --auto --file <report.md> --file <incremental-implementation/SKILL.md> "<prompt>"

The CLI returns non-zero when the agent fails, so the loop's
``AUTOJOB_SELF_HEAL_TEST_COMMAND`` can then guard reopening with the project's tests.
Nothing here touches the browser or the application; it only asks the agent to fix
the code. The session reuses ``AUTOJOB_LLM_MODEL`` by default (mapped to OpenCode's
``openrouter/...`` id); set ``AUTOJOB_SELF_HEAL_REPAIR_MODEL`` to override it,
``AUTOJOB_SELF_HEAL_REPAIR_AGENT`` to pick an OpenCode agent, and
``AUTOJOB_SELF_HEAL_REPAIR_STANDALONE`` to start a private server instead of
attaching to the background one.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT = "report.md"
# The repair agent must land its fix in thin, testable slices; attach the skill so
# it is available even if the session does not pick it up from the skill tool.
SKILL_FILE = PROJECT_ROOT / ".opencode" / "skills" / "incremental-implementation" / "SKILL.md"


def _env(name: str, default: str = "") -> str:
    """Return a stripped environment value, or ``default`` when unset/blank."""
    return (os.environ.get(name) or "").strip() or default


def _truthy(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def build_prompt(
    bundle: Path,
    report: Path,
    bug_id: str,
    fingerprint: str,
    category: str,
) -> str:
    """Build the repair instruction sent to the OpenCode agent."""
    bug = bug_id or "the recorded bug"
    return (
        f"You are the AutoJobApply self-healing repair agent. A live LinkedIn "
        f"Easy Apply run just failed and the self-healing loop stopped on a "
        f"structural error. Fix the code so the same step works next time.\n\n"
        f"Failure: {bug}, category `{category or 'unknown'}`, fingerprint "
        f"`{fingerprint or 'unknown'}`.\n"
        f"Evidence bundle: {bundle}\n"
        f"Attached report: {report}\n"
        f"Required skill: load the `incremental-implementation` skill (its SKILL.md "
        f"is attached: {SKILL_FILE}) and follow it for every change.\n\n"
        f"Read every file in the bundle before changing anything - report.md, "
        f"failure.json, dom.html, page.txt, console.log, and screenshot.png - then "
        f"read the code that produced the failing step.\n\n"
        f"Then follow the AGENTS.md self-healing loop and the "
        f"`incremental-implementation` skill exactly:\n"
        f"1. Find the ROOT CAUSE of the failing Easy Apply step. Do not paper over "
        f"the symptom.\n"
        f"2. Land the fix in thin vertical slices: implement one complete slice, run "
        f"its focused test, verify it, then move to the next slice. Keep every slice "
        f"small (~100 lines) and leave the codebase compilable and green between "
        f"slices.\n"
        f"3. Update every interrelated caller/interpreter in the same slice, and add "
        f"a regression test for the failure (a unit test, or a live-browser test "
        f"when the behaviour depends on real DOM).\n"
        f"4. Record the bug in the matching `known Bugs/` file and update "
        f"`known Bugs/bug_log.md` with symptom, root cause, fix, status, and "
        f"evidence (mark it Fixed only when a test proves it).\n"
        f"5. Run the focused test after each slice, then the relevant suite at the "
        f"end. If a live-browser check is required, run it headlessly.\n\n"
        f"Constraints: never click **Submit application**; do not commit or push; "
        f"keep every source file under 415 lines and split it when it grows past "
        f"that; do not edit files under `task/` without explicit approval. If you "
        f"cannot find the root cause, leave the bug entry Open and explain why "
        f"instead of guessing. Reply with a short summary when you are done."
    )


def resolve_opencode() -> list[str]:
    """Return the argv prefix that runs the OpenCode CLI on this machine."""
    override = _env("AUTOJOB_SELF_HEAL_OPENCODE")
    if override:
        return [override]
    for candidate in ("opencode", "opencode.cmd", "opencode.exe", "opencode.bat"):
        found = shutil.which(candidate)
        if found:
            return [found]
    raise FileNotFoundError(
        "the OpenCode CLI was not found on PATH; set AUTOJOB_SELF_HEAL_OPENCODE to its full path"
    )


def resolve_model() -> str:
    """Model id for the repair session, defaulting to the agent's LLM model.

    ``AUTOJOB_SELF_HEAL_REPAIR_MODEL`` wins. Otherwise reuse ``AUTOJOB_LLM_MODEL``
    so the repair agent thinks with the same model as the rest of the agent; the
    project answers questions through OpenRouter, so an unqualified id gets the
    ``openrouter/`` provider prefix OpenCode expects. Set the explicit variable to
    point at a different provider.
    """
    explicit = _env("AUTOJOB_SELF_HEAL_REPAIR_MODEL")
    if explicit:
        return explicit
    shared = _env("AUTOJOB_LLM_MODEL").strip().strip('"').strip("'")
    if not shared:
        return ""
    return shared if shared.startswith("openrouter/") else f"openrouter/{shared}"


def _bundle_from_env() -> Path:
    bundle = _env("AUTOJOB_FAILURE_BUNDLE")
    if not bundle:
        raise SystemExit(
            "AUTOJOB_FAILURE_BUNDLE is not set; run this script from the "
            "self-healing loop (src.tools.self_healing.recovery)"
        )
    return Path(bundle).expanduser()


def _report_from_env(bundle: Path) -> Path:
    report = _env("AUTOJOB_FAILURE_REPORT")
    return Path(report).expanduser() if report else bundle / DEFAULT_REPORT


def attachments(report: Path) -> list[Path]:
    """Files attached to the repair session: the evidence report, then the skill.

    The ``incremental-implementation`` SKILL.md is attached so the repair agent
    follows thin-slice, test-each-change discipline even when the OpenCode session
    does not resolve the skill from the skill tool.
    """
    files = [report]
    if SKILL_FILE.is_file():
        files.append(SKILL_FILE)
    return files


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        # Line-buffer so the loop's console sees progress while the agent works.
        sys.stdout.reconfigure(line_buffering=True)
    bundle = _bundle_from_env()
    report = _report_from_env(bundle)
    if not report.is_file():
        print(
            f"self-heal repair: the evidence report is missing: {report}",
            file=sys.stderr,
        )
        return 2

    prompt = build_prompt(
        bundle=bundle,
        report=report,
        bug_id=_env("AUTOJOB_BUG_ID"),
        fingerprint=_env("AUTOJOB_FAILURE_FINGERPRINT"),
        category=_env("AUTOJOB_FAILURE_CATEGORY"),
    )

    try:
        argv = resolve_opencode()
    except FileNotFoundError as exc:
        print(f"self-heal repair: {exc}", file=sys.stderr)
        return 2

    argv += ["run", "--auto"]
    if _truthy(_env("AUTOJOB_SELF_HEAL_REPAIR_STANDALONE")):
        argv.append("--standalone")
    model = resolve_model()
    if model:
        argv += ["--model", model]
    agent = _env("AUTOJOB_SELF_HEAL_REPAIR_AGENT")
    if agent:
        argv += ["--agent", agent]
    title = _env("AUTOJOB_SELF_HEAL_REPAIR_TITLE", f"self-heal {_env('AUTOJOB_BUG_ID')}".strip())
    argv += ["--title", title]
    for attachment in attachments(report):
        argv += ["--file", str(attachment)]
    argv.append(prompt)

    print(f"self-heal repair: launching OpenCode for {_env('AUTOJOB_BUG_ID') or 'the failure'}")
    print(f"self-heal repair: bundle {bundle}")
    print(f"self-heal repair: session title {title!r} (watch it in the OpenCode TUI)")
    print(f"self-heal repair: command {' '.join(argv[: len(argv) - 1])} <prompt>")

    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv,
            cwd=str(PROJECT_ROOT),
            env=os.environ.copy(),
            check=False,
        )
    except OSError as exc:
        print(f"self-heal repair: could not launch OpenCode: {exc}", file=sys.stderr)
        return 2

    print(f"self-heal repair: OpenCode finished with exit code {completed.returncode}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
