"""Orchestrate search, matching, and filling through the shared browser run."""

from __future__ import annotations

from uuid import uuid4

from src.configuration import Settings, load_settings
from src.state import (
    AgentOutcome,
    JobAnswerContext,
    JobDescription,
    Task1Outcome,
    Task2Outcome,
    Task4Outcome,
    Task5Outcome,
)
from src.tools.answers import load_answers
from src.tools.browser.primitives import capture_failure_screenshot
from src.tools.browser.profiles import build_browser
from src.tools.browser.runs import (
    _ACTIVE_RUNS,
    _detach_session,
    _Run,
    close_run,
    get_reporter,
    get_run,
    release_run,
)
from src.tools.linkedin_status_overlay import StatusReporter, emit_step


async def start_tasks(
    url: str,
    search_query: str,
    settings: Settings | None = None,
    progress=None,
    open_form: bool = True,
    date_range: str = "",
) -> tuple[AgentOutcome, str | None]:
    """Open one browser session and run Tasks 1-3's interactive steps.

    Returns ``(outcome, run_id)``. When Tasks 1-2 succeed the session is **kept
    open** and registered under ``run_id`` so the resume match and Task 4 can
    continue in the same page; otherwise ``run_id`` is ``None`` and the browser is
    still left open (the agent never closes it).

    ``open_form=False`` is Task 16's match-first flow: select the job and read its
    description but leave Easy Apply closed. The graph then matches a resume and
    calls :func:`open_easy_apply_form` only on a selected resume.

    ``date_range`` is the range the user chose at startup (Task 17). Task 1
    applies it and Task 2 scans it first, falling back to the other range when it
    is exhausted. An empty value keeps the legacy default (**Past 24 hours**).
    """
    # Tasks 1-3 live in their own modules. Imported here (not at module load) so
    # they can share this module's browser primitives without an import cycle.
    from src.tools.linkedin_best_matching_resume import read_job_description
    from src.tools.linkedin_job_selection import (
        _task2_ok,
        _task2_on_page,
        _task2_selected_ok,
    )
    from src.tools.linkedin_search import _task1_ok, _task1_on_page

    settings = settings or load_settings()
    notify = progress or (lambda _message: None)
    # Task 9: one reporter per run. It prints to the CLI (like the old ``notify``)
    # and, once bound to the page, mirrors plain-language agent/LLM status onto an
    # on-page panel. It is stored on the run so later nodes reach it by run id.
    reporter = StatusReporter(emit=notify)
    session = build_browser(settings)
    task1 = Task1Outcome(start_url=url, search_query=search_query)
    task2 = Task2Outcome()
    job_description = JobDescription()
    run_id: str | None = None
    await session.start()
    try:
        page = await session.new_page()
        reporter.bind_page(page)
        emit_step(reporter, "Please wait - starting the browser and opening LinkedIn...")

        task1 = await _task1_on_page(
            page, url, search_query, settings, reporter, date_range=date_range
        )
        if not _task1_ok(task1):
            reporter("Task 1 did not complete; skipping Tasks 2-4.")
            task2.notes = "Task 1 did not complete; Tasks 2-4 were skipped."
            task1.screenshot_path = await capture_failure_screenshot(session, settings, "task1")
        else:
            # Task 1 reports the range it actually applied; use that as both the
            # current range and the preferred range for the first Task 2 scan.
            applied_range = date_range or task1.date_posted_filter_value or ""
            task2 = await _task2_on_page(
                page,
                settings,
                reporter,
                capture=read_job_description,
                open_form=open_form,
                date_range=applied_range,
                preferred_range=applied_range,
            )
            selected = _task2_selected_ok(task2) and (not open_form or _task2_ok(task2))
            if not selected:
                task2.screenshot_path = await capture_failure_screenshot(session, settings, "task2")
            else:
                # Task 2 read the description while the job was open (before any
                # Easy Apply click); only re-read if that produced nothing.
                job_description = task2.job_description or JobDescription()
                if not job_description.is_read:
                    emit_step(reporter, "Please wait - reading the job description...")
                    job_description = await read_job_description(page)
                reporter(
                    "Task 3: read job description "
                    f"(title={job_description.title or '(untitled)'!r}, "
                    f"{len(job_description.body)} description chars)."
                )
                run_id = uuid4().hex
                _ACTIVE_RUNS[run_id] = _Run(session=session, page=page, reporter=reporter)
        return AgentOutcome(task1=task1, task2=task2, job_description=job_description), run_id
    finally:
        if run_id is None:
            # Never close the browser, even when Tasks 1-2 failed: leave the window
            # open so the failure can be inspected. Releasing our CDP handle (not
            # killing) keeps the Chromium process alive.
            await _detach_session(session)


async def fill_application(
    run_id: str | None,
    resume_path: str | None,
    settings: Settings | None = None,
    progress=None,
    context: JobAnswerContext | None = None,
) -> tuple[Task4Outcome, Task5Outcome]:
    """Fill the open Easy Apply form in the session registered under ``run_id``.

    Returns ``(task4, task5)``. ``context`` (Task 12) is the current job + selected
    resume, used to answer job-specific free-text questions; when omitted the fill
    behaves exactly as before. The browser is left open; the caller only releases
    the run (the graph's ``cleanup`` node or :func:`run_full_agent`) — it is never
    closed, so an in-flight session can still be screenshotted on failure.
    """
    # Task 4's fill flow lives in its own module. Imported here (not at module
    # load) so it can share this module's primitives without an import cycle.
    from src.tools.linkedin_easy_apply_fill import _task4_ok, _task4_on_page

    settings = settings or load_settings()
    notify = progress or (lambda _message: None)
    human = Task5Outcome()
    run = get_run(run_id)
    if run is None:
        return (
            Task4Outcome(
                resume_path=resume_path or "",
                notes="browser session is no longer available",
            ),
            human,
        )

    answers = load_answers(settings.answers_file)
    outcome = await _task4_on_page(
        run.page,
        run.session,
        resume_path,
        answers,
        settings,
        notify,
        human=human,
        context=context,
    )
    if not _task4_ok(outcome):
        outcome.screenshot_path = await capture_failure_screenshot(run.session, settings, "task4")
    return outcome, human


async def run_agent(
    url: str,
    search_query: str,
    settings: Settings | None = None,
    progress=None,
) -> AgentOutcome:
    """Run Tasks 1-3 (log in, search, filter, open Easy Apply, read description).

    Task 2 has no inputs of its own: it acts on the job list Task 1 leaves open,
    so both run against the same page. Task 3 then reads the open job's
    description (the resume selection that follows is offline). Each task is
    skipped when the previous one fails. The browser is **left open** at the end
    (the agent never closes it).
    """
    settings = settings or load_settings()
    outcome, run_id = await start_tasks(url, search_query, settings, progress)
    await close_run(run_id)
    return outcome


async def run_full_agent(
    url: str,
    search_query: str,
    settings: Settings | None = None,
    progress=None,
) -> AgentOutcome:
    """Run Tasks 1-4 end-to-end in one browser session (nothing is submitted).

    The job is selected and its description read **before** Easy Apply is opened;
    the form is clicked only after Task 3 selects a resume (Task 16). When Task 4
    reaches the terminal step (only **Submit application** remains) the browser is
    left open and the call waits for the human to close it (see
    :func:`release_run`); otherwise the run is released but the browser is left
    open too (the agent never closes it). This is the one-shot helper used by the
    live integration test; the Task 8 submit-and-repeat loop lives in the graph
    (see :mod:`src.nodes.apply_loop`).
    """
    from src.tools.linkedin_best_matching_resume import ensure_resume  # keep light
    from src.tools.linkedin_easy_apply_open import open_easy_apply_form  # keep light
    from src.tools.linkedin_resume_gate import record_skip, should_skip_job  # keep light

    settings = settings or load_settings()
    outcome, run_id = await start_tasks(
        url, search_query, settings, progress, open_form=False
    )
    if run_id is None:
        return outcome
    # Task 9: reuse the reporter start_tasks created so the on-page panel keeps
    # updating for the resume match and the fill too.
    reporter = get_reporter(run_id) or progress
    try:
        run = get_run(run_id)
        outcome.task3 = await ensure_resume(
            outcome.job_description,
            settings.resumes_dir,
            settings,
            page=run.page if run is not None else None,
            notify=reporter,
        )
        if should_skip_job(outcome.task3, settings):
            outcome.task16 = record_skip(None, outcome.task3, outcome.task2)
        elif outcome.task3.selected_path:
            opened, outcome.task2 = await open_easy_apply_form(
                run.page, settings, reporter, outcome.task2
            )
            if not opened:
                outcome.task4 = Task4Outcome(
                    resume_path=outcome.task3.selected_path,
                    notes=outcome.task2.notes or "Easy Apply form did not open",
                )
                return outcome
            from src.tools.job_context import build_job_context

            description = (
                outcome.job_description
                if outcome.job_description.is_read
                else outcome.task3.job_description
            )
            context = build_job_context(
                description,
                outcome.task3.selected_path,
                settings.resume_descriptions_file,
            )
            outcome.task4, outcome.task5 = await fill_application(
                run_id, outcome.task3.selected_path, settings, reporter, context=context
            )
    finally:
        await release_run(run_id, outcome.task4, settings, reporter)
    return outcome
