"""Task 1 orchestration: log in, search, and apply the results filters.

Runs on an already-open page: waits for the human login gate, performs the
search (including the optional AI detour), selects the **Easy Apply** filter,
then selects **Date posted → Past 24 hours** and re-checks Easy Apply because
the date filter reloads the page. The run stops with a clear note when either
filter cannot be verified; it never opens a job or submits an application.
"""

from __future__ import annotations

from src.configuration import Settings, load_settings
from src.state import Task1Outcome
from src.tools.browser import (
    _append_note,
    _detach_session,
    _pace,
    _safe,
    _wait_for_load,
    build_browser,
    capture_failure_screenshot,
)
from src.tools.linkedin_date_posted import (
    PAST_24_HOURS_VALUE,
    date_posted_filter_applied,
    read_date_controls,
    read_date_options,
    select_past_24_hours,
)
from src.tools.linkedin_search.ai_search import run_ai_job_search_detour
from src.tools.linkedin_search.easy_apply_filter import (
    easy_apply_filter_selected,
    select_easy_apply_filter,
)
from src.tools.linkedin_search.search_box import (
    is_logged_in,
    open_jobs_search,
    wait_for_login,
)
from src.tools.linkedin_status_overlay import emit_step


async def _task1_on_page(
    page,
    url: str,
    search_query: str,
    settings: Settings,
    notify,
) -> Task1Outcome:
    """Run Task 1 steps on an already-open page (no session lifecycle)."""
    outcome = Task1Outcome(start_url=url, search_query=search_query)
    emit_step(notify, "Please wait - opening LinkedIn and waiting for you to log in...")
    await page.goto(url)
    await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)
    await _pace(settings)

    outcome.already_logged_in = await is_logged_in(page)
    if outcome.already_logged_in:
        notify("Already logged in to LinkedIn.")
        emit_step(notify, "Logged in to LinkedIn - starting the job search.")
        outcome.logged_in = True
    else:
        notify(
            "Not logged in yet - please log in using the browser window. "
            f"Waiting up to {settings.session.login_timeout_seconds}s ..."
        )
        emit_step(notify, "Waiting for you - please log in to LinkedIn in the browser window.")
        outcome.logged_in = await wait_for_login(
            page,
            timeout_seconds=settings.session.login_timeout_seconds,
            poll_seconds=settings.session.login_poll_seconds,
        )
        notify(
            "Login detected." if outcome.logged_in else "Login was not detected before the timeout."
        )
    await _pace(settings)

    if outcome.logged_in:
        await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)
        outcome.search_performed = True
        emit_step(notify, f"Please wait - searching for {search_query!r} jobs...")
        found, count, search_url = await open_jobs_search(page, search_query, settings)
        await _pace(settings)
        outcome.results_found = found
        outcome.results_count = count
        outcome.search_url = search_url
        if found:
            emit_step(notify, f"Found {count} job(s) - choosing the Easy Apply ones...")
            await run_ai_job_search_detour(page, search_query, settings, notify, outcome)

            emit_step(notify, "Please wait - selecting the Easy Apply filter...")
            selected, note = await select_easy_apply_filter(page, settings)
            outcome.easy_apply_filter_selected = selected
            outcome.notes = _append_note(outcome.notes, note)

            emit_step(
                notify,
                "Please wait - selecting the Date posted filter (Past 24 hours)...",
            )
            date_selected, date_note = await select_past_24_hours(page, settings)
            outcome.date_posted_filter_selected = date_selected
            if date_selected:
                outcome.date_posted_filter_value = PAST_24_HOURS_VALUE
            else:
                controls = [
                    control.get("label", "")
                    for control in await read_date_controls(page)
                    if any(
                        word in control.get("label", "").lower()
                        for word in ("date", "past", "posted")
                    )
                ]
                options = [
                    option.get("label", "") for option in await read_date_options(page)
                ]
                outcome.notes = _append_note(
                    outcome.notes,
                    "date controls seen: "
                    + ("; ".join(controls[:8]) or "(none)")
                    + "; options seen: "
                    + ("; ".join(options[:8]) or "(none)"),
                )
            outcome.notes = _append_note(outcome.notes, date_note)

            # Applying the date filter reloads the page and can reset the Easy
            # Apply pill. Re-check and re-apply it so Task 2 scans only Easy
            # Apply jobs with both filters active. Applying Easy Apply through
            # the URL (not the pill) preserves f_TPR; a pill click can drop it.
            if not await easy_apply_filter_selected(page):
                emit_step(notify, "Please wait - re-selecting the Easy Apply filter...")
                selected, note = await select_easy_apply_filter(
                    page, settings, prefer_url=True
                )
                outcome.easy_apply_filter_selected = selected
                outcome.notes = _append_note(outcome.notes, note)

                if selected and not await date_posted_filter_applied(page):
                    date_selected, date_note = await select_past_24_hours(page, settings)
                    outcome.date_posted_filter_selected = date_selected
                    outcome.date_posted_filter_value = (
                        PAST_24_HOURS_VALUE if date_selected else ""
                    )
                    outcome.notes = _append_note(outcome.notes, date_note)

            # Final date check: the range must still be applied to the results
            # (not just checked in a popover) before Task 2 starts.
            if outcome.date_posted_filter_selected and not await date_posted_filter_applied(
                page
            ):
                date_selected, date_note = await select_past_24_hours(page, settings)
                outcome.date_posted_filter_selected = date_selected
                outcome.date_posted_filter_value = (
                    PAST_24_HOURS_VALUE if date_selected else ""
                )
                outcome.notes = _append_note(outcome.notes, date_note)
                if date_selected and not await easy_apply_filter_selected(page):
                    selected, note = await select_easy_apply_filter(
                        page, settings, prefer_url=True
                    )
                    outcome.easy_apply_filter_selected = selected
                    outcome.notes = _append_note(outcome.notes, note)

            # Final combined check: both filters must be active together before
            # Task 2 starts. Re-selecting Easy Apply through the URL keeps f_TPR.
            if outcome.easy_apply_filter_selected and not await easy_apply_filter_selected(
                page
            ):
                selected, note = await select_easy_apply_filter(
                    page, settings, prefer_url=True
                )
                outcome.easy_apply_filter_selected = selected
                outcome.notes = _append_note(outcome.notes, note)
                if selected and not await date_posted_filter_applied(page):
                    outcome.date_posted_filter_selected = False
                    outcome.date_posted_filter_value = ""
                    outcome.notes = _append_note(
                        outcome.notes,
                        "the date filter was lost while re-selecting Easy Apply",
                    )

    outcome.page_url = await _safe(page.get_url(), None)
    outcome.page_title = await _safe(page.get_title(), "") or ""
    return outcome


def _task1_ok(outcome: Task1Outcome) -> bool:
    return bool(
        outcome.logged_in
        and outcome.results_found
        and outcome.easy_apply_filter_selected
        and outcome.date_posted_filter_selected
    )


async def run_task1(
    url: str,
    search_query: str,
    settings: Settings | None = None,
    progress=None,
) -> Task1Outcome:
    """Run Task 1 only: log in (waiting for the user if needed), search, filter."""
    settings = settings or load_settings()
    notify = progress or (lambda _message: None)
    session = build_browser(settings)
    try:
        await session.start()
        page = await session.new_page()
        outcome = await _task1_on_page(page, url, search_query, settings, notify)
        if not _task1_ok(outcome):
            outcome.screenshot_path = await capture_failure_screenshot(session, settings, "task1")
        return outcome
    finally:
        # Never close the browser (see browser.close_run): release our handle and
        # leave the Chromium window open even when Task 1 failed.
        await _detach_session(session)


__all__ = ["_task1_ok", "_task1_on_page", "run_task1"]
