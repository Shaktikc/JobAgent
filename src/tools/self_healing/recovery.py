"""Close a failed browser session and reopen the same Easy Apply job.

The recovery layer only touches the run it was given. It never kills every browser
using the profile: that escape hatch stays in ``autojob --clean-profile``. If the
old session cannot be confirmed closed, recovery stops rather than launching a
second browser against a locked profile.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from src.configuration import PROJECT_ROOT, Settings
from src.date_range import PAST_24_HOURS_TPR, date_range_tpr_for
from src.state import DEFAULT_LOGIN_URL, JobDescription, Task2Outcome
from src.tools.self_healing.models import CapturedFailure, FailureRecord, JobTarget

CommandFn = Callable[[str, Path, dict[str, str], float], Awaitable[tuple[int, str]]]


@dataclass
class ReopenResult:
    """The fresh browser run opened for the same job."""

    run_id: str = ""
    task2: Task2Outcome | None = None
    description: JobDescription | None = None
    reason: str = ""

    @property
    def opened(self) -> bool:
        return bool(self.run_id and self.task2 is not None)


def _normalized(text: str) -> str:
    return " ".join((text or "").lower().split())


async def close_run_force(run_id: str | None, settings: Settings) -> tuple[bool, str]:
    """Force-close one registered run and wait for its profile lock to clear.

    ``session.kill()`` (not ``stop()``) is deliberate: the self-healing loop must
    not inherit stale CDP state. The wait is bounded by
    ``AUTOJOB_SELF_HEAL_CLOSE_TIMEOUT_SECONDS``; a browser that is still alive
    makes this return ``False`` and the loop stops instead of opening a second
    browser against the same profile.
    """
    if not run_id:
        return True, "no browser run was registered"

    from src.tools.browser import (
        _clear_profile_locks,
        _profile_browser_pids,
        forget_run,
        get_run,
    )

    run = get_run(run_id)
    if run is None:
        return True, "the browser run was already released"

    session = run.session
    timeout = settings.self_healing.close_timeout_seconds
    detail = ""
    kill = getattr(session, "kill", None)
    if callable(kill):
        try:
            await asyncio.wait_for(kill(), timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - report, then verify the process
            detail = f"session.kill() failed: {exc}"
    else:
        detail = "the session has no kill() method"

    deadline = time.monotonic() + timeout
    pids: list[int] = []
    while True:
        pids = await asyncio.to_thread(_profile_browser_pids, settings.profile_dir)
        if not pids or time.monotonic() >= deadline:
            break
        await asyncio.sleep(0.25)

    if pids:
        # Keep the run registered so cleanup can still release/detach it for the
        # human; never launch a second browser against a locked profile.
        return (
            False,
            (detail + "; " if detail else "")
            + "browser process(es) still own the profile: "
            + ", ".join(str(pid) for pid in pids),
        )

    forget_run(run_id)
    with contextlib.suppress(OSError):
        _clear_profile_locks(settings.profile_dir)
    return True, detail or "browser closed and profile lock cleared"


async def _click_easy_apply(
    page,
    settings: Settings,
    target: JobTarget,
    notify,
) -> tuple[bool, Task2Outcome]:
    """Click the details pane's Easy Apply button and wait for the form."""
    from src.tools.browser import _safe
    from src.tools.linkedin import looks_like_easy_apply_action
    from src.tools.linkedin_job_apply_button import (
        wait_for_easy_apply_modal,
        wait_for_job_apply_button,
    )

    task2 = Task2Outcome(job_title=target.title, page_url=await _safe(page.get_url(), None))
    button, label = await wait_for_job_apply_button(page, settings)
    if button is None or not looks_like_easy_apply_action(label):
        task2.notes = "no Easy Apply button on the reopened job"
        return False, task2
    task2.easy_apply_button_found = True
    try:
        await _safe(button.evaluate("() => this.scrollIntoView({block: 'center'})"))
        await button.click()
    except Exception as exc:  # noqa: BLE001 - report why the reopen failed
        task2.notes = f"Easy Apply click failed: {exc}"
        return False, task2
    task2.easy_apply_clicked = True
    opened, modal_text = await wait_for_easy_apply_modal(page, settings)
    task2.application_form_opened = opened
    task2.modal_text = modal_text
    if not opened:
        task2.notes = "Easy Apply form did not reopen"
        return False, task2
    notify(f"self-heal: reopened the Easy Apply form for {target.title or 'the job'}.")
    return True, task2


async def _open_target(
    page,
    target: JobTarget,
    settings: Settings,
    notify,
) -> tuple[bool, Task2Outcome]:
    """Navigate to the recorded job URL (or find its card) and open the form."""
    from src.tools.browser import _wait_for_load
    from src.tools.linkedin_job_apply_button import pane_shows_job, read_details_pane_job
    from src.tools.linkedin_job_selection import find_card_by_title, open_job_card

    task2 = Task2Outcome(job_title=target.title)
    url = (target.url or "").strip()
    if url.startswith(("http://", "https://", "file:")):
        notify("self-heal: reopening the recorded page URL...")
        await page.goto(url)
        await _wait_for_load(page, settings.session.easy_apply_timeout_seconds)
        pane_title = await read_details_pane_job(page)
        if not target.title or pane_shows_job(pane_title, target.title):
            opened, task2 = await _click_easy_apply(page, settings, target, notify)
            if opened:
                return True, task2
        else:
            task2.notes = f"the job URL shows {pane_title!r}, not {target.title!r}"

    title = (target.title or "").strip()
    if not title:
        task2.notes = "no target job URL or title was recorded"
        return False, task2

    cards = await find_card_by_title(page, title)
    if cards is None:
        query = quote_plus(target.search_query or title)
        range_tpr = date_range_tpr_for(target.date_range) or PAST_24_HOURS_TPR
        notify("self-heal: the job was not on the current list; searching again...")
        u = (
            f"https://www.linkedin.com/jobs/search/?keywords={query}"
            f"&f_AL=true&f_TPR={range_tpr}"
        )
        await page.goto(u)
        await _wait_for_load(page, settings.session.easy_apply_timeout_seconds)
        deadline = time.monotonic() + settings.session.easy_apply_timeout_seconds
        while time.monotonic() < deadline:
            cards = await find_card_by_title(page, title)
            if cards is not None:
                break
            await asyncio.sleep(0.5)
    if cards is None:
        task2.notes = f"job {title!r} was not found after reopening the browser"
        return False, task2

    opened, pane_title = await open_job_card(page, cards, title, settings, notify)
    if not opened:
        task2.notes = f"the details pane still shows {pane_title or 'another job'}"
        return False, task2
    return await _click_easy_apply(page, settings, target, notify)


async def reopen_same_job(
    target: JobTarget,
    settings: Settings,
    progress=None,
) -> ReopenResult:
    """Start a fresh browser and reopen ``target`` (never a different job)."""
    notify = progress or (lambda _message: None)
    from src.tools.browser import get_run, start_tasks
    from src.tools.linkedin_best_matching_resume import read_job_description

    notify("self-heal: launching a fresh browser and returning to the same job...")
    start_kwargs: dict = {}
    if target.date_range:
        start_kwargs["date_range"] = target.date_range
    outcome, run_id = await start_tasks(
        target.login_url or DEFAULT_LOGIN_URL,
        target.search_query or "",
        settings,
        notify,
        **start_kwargs,
    )
    if not run_id:
        reason = outcome.task2.notes or outcome.task1.notes or "browser launch failed"
        return ReopenResult(reason=f"could not reopen the browser: {reason}")

    run = get_run(run_id)
    if run is None:
        return ReopenResult(reason="the fresh browser run was not registered")
    try:
        opened, task2 = await _open_target(run.page, target, settings, notify)
        if not opened:
            await close_run_force(run_id, settings)
            return ReopenResult(reason=task2.notes or "the same job did not reopen")

        from src.tools.linkedin_job_apply_button import pane_shows_job

        description = outcome.job_description or JobDescription()
        if not description.title or (
            target.title and not pane_shows_job(description.title, target.title)
        ):
            description = await read_job_description(run.page)
        task2.job_description = description
        task2.page_url = task2.page_url or await run.page.get_url()
        return ReopenResult(run_id=run_id, task2=task2, description=description)
    except Exception as exc:  # noqa: BLE001 - the loop records the reopen failure
        await close_run_force(run_id, settings)
        return ReopenResult(reason=f"reopening the job failed: {exc}")


def job_target_from_state(state: dict) -> JobTarget:
    """Build the same-job target from graph state."""
    description = state.get("job_description") or JobDescription()
    task2 = state.get("task2")
    title = (task2.job_title if task2 is not None else "") or description.title or ""
    url = description.page_url or (task2.page_url if task2 is not None else "") or ""
    return JobTarget(
        url=url,
        title=title,
        company=description.company or "",
        search_query=state.get("search_query") or "",
        login_url=state.get("url") or "",
        date_range=state.get("date_range") or "",
    )


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
    "src.tools.linkedin_status_overlay",
    # Reload browser before the modules that import its primitives at load time.
    "src.tools.browser",
    "src.tools.linkedin_skip_applied",
    "src.tools.linkedin_pagination",
    "src.tools.linkedin_job_apply_button",
    "src.tools.linkedin_job_selection",
    "src.tools.linkedin_search",
    "src.tools.linkedin_easy_apply_fill.form_queries.scripts",
    "src.tools.linkedin_easy_apply_fill.form_queries.readers",
    "src.tools.linkedin_easy_apply_fill.form_queries",
    "src.tools.linkedin_easy_apply_fill.field_filling",
    "src.tools.linkedin_easy_apply_fill.checkbox_groups",
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


__all__ = [
    "CommandFn",
    "ReopenResult",
    "close_run_force",
    "job_target_from_state",
    "reload_runtime_modules",
    "reopen_same_job",
    "run_repair_and_test",
]
