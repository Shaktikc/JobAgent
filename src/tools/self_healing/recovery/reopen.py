"""Close a failed browser session and reopen the same Easy Apply job.

The recovery layer only touches the run it was given. It never kills every browser
using the profile: that escape hatch stays in ``autojob --clean-profile``. If the
old session cannot be confirmed closed, recovery stops rather than launching a
second browser against a locked profile.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass
from urllib.parse import quote_plus

from src.configuration import Settings
from src.date_range import PAST_24_HOURS_TPR, date_range_tpr_for
from src.state import DEFAULT_LOGIN_URL, JobDescription, Task2Outcome
from src.tools.self_healing.models import JobTarget


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
