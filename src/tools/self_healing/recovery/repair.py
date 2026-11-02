"""Run the configured repair command and its tests after a self-heal failure.

The repair command runs in a subprocess; :func:`reload_runtime_modules` reloads
the browser/fill stack afterwards so a repaired source edit is visible to the
still-running process before the loop retries.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from src.configuration import PROJECT_ROOT, Settings
from src.tools.self_healing.models import CapturedFailure, FailureRecord

CommandFn = Callable[[str, Path, dict[str, str], float], Awaitable[tuple[int, str]]]


async def _run_command(
    command: str,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    on_line: Callable[[str], None] | None = None,
) -> tuple[int, str]:
    """Run a configured shell command and return ``(returncode, combined output)``.

    Output streams to ``on_line`` as it arrives (a long agentic repair must not be a
    silent black box) and is returned whole for the repair/test log.
    """
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=str(cwd),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    collected: list[str] = []

    async def pump() -> None:
        assert process.stdout is not None
        async for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace")
            collected.append(line)
            if on_line is not None:
                with contextlib.suppress(Exception):
                    on_line(line.rstrip("\r\n"))

    try:
        await asyncio.wait_for(asyncio.gather(pump(), process.wait()), timeout=timeout)
    except TimeoutError:
        with contextlib.suppress(Exception):
            process.kill()
        with contextlib.suppress(Exception):
            await process.communicate()
        return -1, f"command timed out after {timeout:.0f}s: {command}"
    return process.returncode or 0, "".join(collected)


def _print_repair_line(line: str) -> None:
    """Echo one repair/test output line to the run console as it arrives."""
    print(f"self-heal: {line}", flush=True)


# Modules a repair may have changed; reload before retry (state/graph excluded).
_RUNTIME_MODULES = (
    "src.tools.self_healing.fingerprint",
    "src.tools.self_healing.capture",
    "src.tools.self_healing.buglog",
    "src.tools.forms",
    "src.tools.answers",
    "src.tools.linkedin",
    "src.tools.linkedin_status_overlay.panel_js",
    "src.tools.linkedin_status_overlay.interaction_lock",
    "src.tools.linkedin_status_overlay.status_reporter",
    "src.tools.linkedin_status_overlay",
    # Reload browser before the modules that import its primitives at load time.
    "src.tools.browser",
    "src.tools.linkedin_skip_applied",
    "src.tools.linkedin_pagination",
    "src.tools.linkedin_job_apply_button",
    "src.tools.linkedin_job_selection",
    "src.tools.linkedin_search",
    "src.tools.linkedin_easy_apply_fill.question_labels",
    "src.tools.linkedin_easy_apply_fill.required_only",
    "src.tools.linkedin_easy_apply_fill.checkbox_groups",
    "src.tools.linkedin_easy_apply_fill.form_queries.scripts",
    "src.tools.linkedin_easy_apply_fill.form_queries.readers",
    "src.tools.linkedin_easy_apply_fill.form_queries",
    "src.tools.linkedin_easy_apply_fill.field_filling",
    "src.tools.linkedin_easy_apply_fill.resume_attachment",
    "src.tools.linkedin_easy_apply_fill.form_walk",
    "src.tools.linkedin_easy_apply_fill",
    "src.tools.linkedin_apply_loop",
)


def reload_runtime_modules() -> list[str]:
    """Reload the browser/fill stack after an external repair command.

    The repair command runs in a subprocess, so a source edit is only visible to
    this process after its modules are reloaded. The browser is closed at this
    point (the run registry is empty), so resetting ``src.tools.browser`` is safe.
    Returns a list of reload failures; a non-empty list means the loop must stop
    rather than retry with stale code.
    """
    failures: list[str] = []
    for name in _RUNTIME_MODULES:
        try:
            importlib.reload(importlib.import_module(name))
        except Exception as exc:  # noqa: BLE001 - report which module is stale
            failures.append(f"{name}: {exc}")
    return failures


async def _run_configured(
    command_fn: CommandFn,
    command: str,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
) -> tuple[int, str]:
    """Stream the built-in runner; injected test fakes keep their small signature."""
    if command_fn is _run_command:
        return await _run_command(command, cwd, env, timeout, on_line=_print_repair_line)
    return await command_fn(command, cwd, env, timeout)


async def run_repair_and_test(
    settings: Settings,
    captured: CapturedFailure,
    record: FailureRecord,
    notify,
    command_fn: CommandFn | None = None,
) -> tuple[bool, str]:
    """Run the optional repair command, then its tests, before any reopen."""
    command_fn = command_fn or _run_command
    command = (settings.self_healing.repair_command or "").strip()
    if not command:
        notify(
            "self-heal: no repair command configured - closing and reopening only "
            "(the code is not changed)."
        )
        return True, "skipped (no repair command configured) - runtime recovery only"

    bundle = Path(record.bundle_dir or captured.bundle_dir)
    bundle.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "AUTOJOB_FAILURE_BUNDLE": str(bundle),
        "AUTOJOB_FAILURE_REPORT": str(bundle / "report.md"),
        "AUTOJOB_FAILURE_FINGERPRINT": captured.fingerprint,
        "AUTOJOB_FAILURE_CATEGORY": captured.category,
        "AUTOJOB_BUG_ID": record.bug_id,
        # Task 14: the configured self-healing model wins for the spawned
        # OpenCode session. It is independent of AUTOJOB_LLM_MODEL (the
        # general-purpose model), which this command must never substitute.
        "AUTOJOB_SELF_HEAL_REPAIR_MODEL": settings.self_healing.repair_model,
    }
    timeout = settings.self_healing.command_timeout_seconds

    notify(f"self-heal: running the repair command for {record.bug_id or 'the failure'}...")
    notify("self-heal: streaming the repair agent's output below...")
    code, repair_output = await _run_configured(command_fn, command, PROJECT_ROOT, env, timeout)
    (bundle / "repair.log").write_text(repair_output, encoding="utf-8")
    if code != 0:
        return False, f"repair command failed with exit code {code}"

    test_command = (settings.self_healing.test_command or "uv run pytest -q").strip()
    notify(f"self-heal: running tests before reopening: {test_command}")
    code, test_output = await _run_configured(command_fn, test_command, PROJECT_ROOT, env, timeout)
    (bundle / "tests.log").write_text(test_output, encoding="utf-8")
    if code != 0:
        return False, f"tests failed with exit code {code} after the repair"
    return True, "repair command and tests passed"
