"""Shared browser-use primitives for the LinkedIn agent.

Task 1 (log in, search "software engineer", click LinkedIn's optional "Try AI job
search", and select the **Easy Apply** filter) lives in
:mod:`src.tools.linkedin_search`; Task 2 (select a job from the results list and
open its **Easy Apply** form) lives in :mod:`src.tools.linkedin_job_selection`;
Task 3 (read the open job's description and pick the best-matching resume) lives in
:mod:`src.tools.linkedin_best_matching_resume`; Task 4 (enumerate the open Easy
Apply form, answer each question via the LLM in Task 4.1, attach the Task 3
resume, and advance through multi-step forms — stopping before **Submit
application**) lives in
:mod:`src.tools.linkedin_easy_apply_fill`; Task 5 (ask the human for an unknown
answer, remember it, and show a browser feedback banner) lives in
:mod:`src.tools.linkedin_ask_human`; Task 6 (skip jobs already marked
**Applied**) lives in :mod:`src.tools.linkedin_skip_applied`; Task 7 (when a whole
results page is Applied, advance to the next page) lives in
:mod:`src.tools.linkedin_pagination`; Task 8 (wait for the human's submission and
open the next job) lives in :mod:`src.tools.linkedin_apply_loop`.
This module owns the shared browser primitives. For back-compat the moved names
are still reachable here (see ``__getattr__`` below), so ``browser`` remains the
stable entry point.

The interaction uses browser-use's deterministic CDP actor API (``Page`` /
``Element``); the LLM (Task 4.1) only chooses answers, it never drives the
browser.

A live session is kept open across graph nodes via :func:`start_tasks` (which
registers it) and :func:`fill_application` / :func:`close_run`. The state only
carries an opaque ``browser_run_id`` string, so nothing un-serializable leaks into
the graph.

The heavy ``browser`` extra is only needed for real runs, so this module is
imported lazily by the graph nodes:

    uv sync --extra browser
    uvx playwright install chromium
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from src.configuration import Settings, load_settings
from src.state import (
    AgentOutcome,
    JobDescription,
    Task1Outcome,
    Task2Outcome,
    Task4Outcome,
    Task5Outcome,
)
from src.tools.answers import load_answers

_INSTALL_HINT = (
    "browser-use is not installed. Enable the optional extra:\n"
    "  uv sync --extra browser\n"
    "  uvx playwright install chromium"
)

# Attribute used to mark AI/semantic job cards (div[role="button"]) so the
# classic selectors and CDP element resolution can find them. Also used by
# :mod:`src.tools.linkedin_job_selection` (Task 2).
_JOB_CARD_ATTR = "data-autojob-card"

# How long to keep waiting for the results list to render after a search.
_RESULTS_WAIT_SECONDS = 20.0
# Poll interval used while waiting for the details pane / apply modal.
_APPLY_POLL_SECONDS = 0.5

_RESULTS_QUERY = """
() => JSON.stringify({
  count: document.querySelectorAll(
    'li.jobs-search-results__list-item, li.scaffold-layout__list-item, '
    + 'div.job-card-container, div.jobs-search-results-list__list-item, '
    + 'ul.jobs-search__results-list > li'
  ).length
})
"""

# LinkedIn's AI/semantic results page (origin=SEMANTIC_SEARCH_LANDING_PAGE)
# renders its job cards as div[role="button"], not the classic <li> items the
# classic selectors above match. Scan those controls and mark the ones that look
# like job cards with `data-autojob-card` (see _JOB_CARD_ATTR), so results_count
# and read_job_cards can find them and the run never stalls waiting for cards
# that the classic selectors cannot see.
_AI_JOB_CARDS_JS = r"""
() => {
  // Clear any stale markers from a previous scan.
  document.querySelectorAll('[data-autojob-card]').forEach(
    (el) => el.removeAttribute('data-autojob-card')
  );
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  let n = 0;
  document.querySelectorAll('div[role="button"]').forEach((el) => {
    const t = norm(el.innerText);
    if (!t || t.length < 40) return;              // a card has a title + metadata
    if (/^easy apply/i.test(t)) return;           // not the apply button / filter
    if (!/(on-site|hybrid|remote|posted|actively reviewing|applied|promoted)/i.test(t)) return;
    el.setAttribute('data-autojob-card', 'job' + n);
    n += 1;
  });
  return JSON.stringify({ count: n });
}
"""


# Locate the open Easy Apply surface (shared by Tasks 2 and 4). LinkedIn renders
# it in one of two ways:
#   * the classic artdeco dialog (``.jobs-easy-apply-modal`` / ``.artdeco-modal``),
#   * or, on the AI/semantic job view, an **inline** full-page form whose classes
#     are hashed (no artdeco classes), identified by the "Apply to <company>"
#     heading and its application controls.
# This snippet is injected into a query and defines ``findApplyRoot()``, which
# returns the container element for either form (or ``null`` when none is open).
FIND_APPLY_ROOT_JS = r"""
  const findApplyRoot = () => {
    const isVisible = (el) => !!el && el.getClientRects().length > 0;
    const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
    // 1) The classic Easy Apply dialog. A page can also carry unrelated, hidden
    //    dialogs (e.g. "Save this job") earlier in the DOM, so never trust the
    //    first match: prefer the Easy Apply dialog, then the first *visible*
    //    dialog holding form controls or Easy Apply text.
    const candidates = Array.from(document.querySelectorAll(
      'div.jobs-easy-apply-modal, div[role="dialog"].artdeco-modal, '
      + '.artdeco-modal--layer-default, div[data-test-modal-container], .artdeco-modal'
    ));
    const easy = candidates.find((el) => el.classList.contains('jobs-easy-apply-modal'));
    if (easy && isVisible(easy)) return easy;
    const visible = candidates.filter(isVisible);
    const applyish = visible.find((el) => /easy apply|application/i.test(el.innerText || ''));
    const formish = visible.find((el) => el.querySelector(
      'input:not([type=hidden]), textarea, select, [role="radio"], [role="checkbox"]'
    ));
    const dialog = applyish || formish || visible[0] || easy || null;
    if (dialog) return dialog;

    // 2) The inline full-page form. Anchor on an application control (a phone
    //    field or a select holding an email), then climb to the closest ancestor
    //    that also holds a navigation/submit button.
    const anchor = Array.from(document.querySelectorAll('input[type="tel"], select'))
      .filter(isVisible)
      .find((el) => (el.getAttribute('type') || '').toLowerCase() === 'tel'
        || /@/.test(el.value || ''));
    const heading = Array.from(document.querySelectorAll('h1, h2, h3, h4'))
      .find((h) => /^apply to\b/i.test(norm(h.innerText)));
    if (!anchor && !heading) return null;
    let el = anchor || heading;
    for (let i = 0; i < 16 && el; i++) {
      const hasNav = Array.from(el.querySelectorAll('button, [role="button"]')).some((b) =>
        /next|continue|submit application|review/i.test(
          norm(b.innerText) + ' ' + (b.getAttribute('aria-label') || '')
        )
      );
      if (hasNav && (!anchor || el.contains(anchor))) return el;
      el = el.parentElement;
    }
    return heading || null;
  };
"""


@dataclass
class _Run:
    """A live browser session kept open across graph nodes."""

    session: object
    page: object


# run_id -> live session, so Tasks 2-4 can share one browser window without
# putting the (un-serializable) session object into the graph state.
_ACTIVE_RUNS: dict[str, _Run] = {}


def _require_browser_use():
    """Import browser-use on demand, with an actionable error if missing."""
    try:
        from browser_use import Browser
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(_INSTALL_HINT) from exc
    return Browser


async def _safe(awaitable, default=None):
    """Await ``awaitable``, returning ``default`` if it raises."""
    try:
        return await awaitable
    except Exception:  # noqa: BLE001 - best-effort probing of a live page
        return default


async def _pace(settings: Settings) -> None:
    """Pause between visible steps so a human can follow the run.

    A no-op unless ``AUTOJOB_SESSION_STEP_DELAY_SECONDS`` is set; used by the
    slow-motion demo/test run.
    """
    delay = settings.session.step_delay_seconds
    if delay:
        await asyncio.sleep(delay)


def _loads(raw: str) -> dict:
    """Parse a JSON payload returned by ``page.evaluate``, tolerating noise."""
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# Chromium single-instance files left in the user-data-dir. While a browser owns
# the profile it holds a lock; a crashed/interrupted run can leave the lock files
# behind without a process.
_PROFILE_LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile")


def _profile_is_locked(profile_dir: Path) -> bool:
    """True when the profile looks owned by a browser (or a crashed one).

    A lock file alone does not prove the browser is gone: on Windows a *live*
    Chromium holds ``lockfile`` for as long as it runs. Callers that need to act
    on the lock must therefore also check :func:`_profile_browser_pids`.
    """
    return any((profile_dir / name).exists() for name in _PROFILE_LOCK_FILES)


def _clear_profile_locks(profile_dir: Path) -> None:
    """Remove Chromium's single-instance files so a fresh launch can take over."""
    for name in _PROFILE_LOCK_FILES:
        with contextlib.suppress(OSError):
            path = profile_dir / name
            if path.is_symlink() or path.exists():
                path.unlink()


def _profile_browser_pids(profile_dir: Path) -> list[int]:
    """Best-effort PIDs of chrome/chromium processes using this exact profile."""
    target = str(profile_dir)
    if sys.platform == "win32":
        script = (
            "$ErrorActionPreference='SilentlyContinue';"
            "Get-CimInstance Win32_Process -Filter "
            "\"Name='chrome.exe' OR Name='chromium.exe' OR Name='headless_shell.exe'\" | "
            "Where-Object { $_.CommandLine -like ('*' + $env:AUTOJOB_PROFILE + '*') } | "
            "ForEach-Object { $_.ProcessId }"
        )
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
        env = {**os.environ, "AUTOJOB_PROFILE": target}
    else:
        cmd = ["pgrep", "-f", target]
        env = None
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=20, env=env, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(line) for line in result.stdout.splitlines() if line.strip().isdigit()]


def terminate_profile_browsers(profile_dir: Path) -> int:
    """Kill every browser still holding ``profile_dir``; return how many.

    This is the **explicit** escape hatch (the ``--clean-profile`` command and
    :func:`clean_profile`). It is intentionally aggressive: it force-closes any
    browser whose command line references this dedicated profile, including a
    live one. Automatic recovery must **not** call it — force-killing a browser
    that another run is driving makes that run's CDP WebSocket drop and every
    reconnect fail (``ConnectionRefusedError``). Only processes whose command
    line references this dedicated profile are touched, so a normal Chrome is
    never affected.
    """
    pids = _profile_browser_pids(profile_dir)
    for pid in pids:
        if sys.platform == "win32":
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
        else:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)
    return len(pids)


def clean_profile(settings: Settings) -> int:
    """Close every browser using the profile and clear its lock files.

    Explicit and destructive: used by ``autojob --clean-profile`` when the user
    wants to force-recover a profile, even if a browser is still driving it.
    """
    settings.profile_dir.mkdir(parents=True, exist_ok=True)
    killed = terminate_profile_browsers(settings.profile_dir)
    _clear_profile_locks(settings.profile_dir)
    return killed


def build_browser(settings: Settings):
    """Build a Chromium session that persists logins in ``data/profile``.

    A profile lock left by a **crashed** run is recovered by clearing the stale
    lock files. A lock held by a **live** browser is never force-killed: doing so
    was the cause of a second run tearing down the first run's CDP WebSocket
    (``CDP WebSocket message handler exited`` followed by reconnection attempts
    that fail with ``ConnectionRefusedError`` / ``WinError 1225``). Instead the
    launch stops with an actionable error so the caller can finish or close the
    other run (or the user can run ``autojob --clean-profile`` deliberately).
    """
    Browser = _require_browser_use()
    settings.profile_dir.mkdir(parents=True, exist_ok=True)
    if settings.session.clean_stale_profile and _profile_is_locked(settings.profile_dir):
        live = _profile_browser_pids(settings.profile_dir)
        if live:
            pids = ", ".join(str(pid) for pid in live)
            raise RuntimeError(
                "another browser is already using the AutoJobApply profile "
                f"{settings.profile_dir} (process id(s): {pids}). Close that "
                "window (or wait for the other run to finish), then retry; to "
                "force-close it run `autojob --clean-profile`."
            )
        # The lock has no live owner: a crashed/interrupted run left it behind.
        # Clearing it lets this launch open its own CDP port instead of handing
        # off to a browser that no longer exists.
        _clear_profile_locks(settings.profile_dir)
    return Browser(
        headless=settings.session.headless,
        user_data_dir=str(settings.profile_dir),
        viewport=settings.session.viewport,
        user_agent=settings.session.user_agent,
    )


async def _wait_for_load(page, timeout_seconds: float) -> bool:
    """Poll until the page reports ``document.readyState == 'complete'``."""
    deadline = time.monotonic() + max(timeout_seconds, 0)
    while time.monotonic() < deadline:
        if await _safe(page.evaluate("() => document.readyState")) == "complete":
            return True
        await asyncio.sleep(0.25)
    return False


async def _element_label(element) -> str:
    """Best-effort accessible label for a candidate control."""
    for attribute in ("aria-label", "placeholder"):
        label = await _safe(element.get_attribute(attribute), "") or ""
        if label:
            return label
    return await _safe(element.evaluate("() => this.innerText"), "") or ""


async def _element_is_choice_control(element) -> bool:
    """True when the control is the results *filter* toggle, not an apply button.

    LinkedIn renders the "Easy Apply" results filter pill as a choice toggle: it
    is ``role="radio"`` carrying ``aria-checked`` (or a plain toggle carrying
    ``aria-pressed``). A job's "Easy Apply" apply button is a plain
    ``artdeco-button`` and has neither. This structural signal — not the label,
    which both controls share — is what tells the two apart on the real page.
    """
    if await _safe(element.get_attribute("aria-checked"), None) is not None:
        return True
    return await _safe(element.get_attribute("aria-pressed"), None) is not None


async def _element_is_apply_button(element) -> bool:
    """True when the control is a job's "Easy Apply" apply button, not the filter.

    LinkedIn marks the blue apply button with the ``jobs-apply-button`` class
    (and a ``data-live-test-job-apply-button`` hook), which the results filter
    pill never carries. This lets the filter finder skip it even when its
    accessible name also contains "Easy Apply".
    """
    css_class = await _safe(element.get_attribute("class"), "") or ""
    if "jobs-apply-button" in css_class:
        return True
    return await _safe(element.get_attribute("data-live-test-job-apply-button"), None) is not None


async def _query_elements(page, selector: str) -> list:
    try:
        return list(await page.get_elements_by_css_selector(selector))
    except Exception:  # noqa: BLE001 - selector may not match in this DOM
        return []


async def _first_element(page, selectors):
    """Return the first matching element across ``selectors``, or ``None``."""
    for selector in selectors:
        elements = await _query_elements(page, selector)
        if elements:
            return elements[0]
    return None


async def results_count(page) -> int:
    """Number of job cards currently rendered on the search results page."""
    payload = _loads(await _safe(page.evaluate(_RESULTS_QUERY), ""))
    try:
        count = int(payload.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count == 0:
        # AI/semantic results page: its job cards are div[role="button"], which
        # the classic selectors in _RESULTS_QUERY cannot see.
        count = await _mark_ai_job_cards(page)
    return count


async def _mark_ai_job_cards(page) -> int:
    """Mark AI/semantic job-card controls and return how many were found.

    LinkedIn's AI job search renders results as ``div[role="button"]`` job cards
    that the classic ``<li>`` selectors miss. This tags each one with
    ``data-autojob-card`` (see :data:`_JOB_CARD_ATTR`) so ``read_job_cards`` can
    resolve them, and returns the count for :func:`results_count`.
    """
    payload = _loads(await _safe(page.evaluate(_AI_JOB_CARDS_JS), ""))
    try:
        return int(payload.get("count") or 0)
    except (TypeError, ValueError):
        return 0


def _append_note(existing: str, extra: str) -> str:
    return f"{existing}; {extra}" if existing else extra


async def _marker_element(page, attribute: str, marker: str):
    return await _first_element(page, [f'[{attribute}="{marker}"]'])


async def capture_failure_screenshot(
    session, settings: Settings, name: str = "task1"
) -> str | None:
    """Write a full-page PNG for debugging and return its path."""
    settings.debug_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = settings.debug_dir / f"{name}-failure-{stamp}.png"
    with contextlib.suppress(Exception):
        await session.take_screenshot(path=str(path), full_page=True)
    return str(path) if path.is_file() else None


async def start_tasks(
    url: str,
    search_query: str,
    settings: Settings | None = None,
    progress=None,
) -> tuple[AgentOutcome, str | None]:
    """Open one browser session and run Tasks 1-3's interactive steps.

    Returns ``(outcome, run_id)``. When Tasks 1-2 succeed the session is **kept
    open** and registered under ``run_id`` so Task 4 can fill the same Easy Apply
    form; otherwise the session is closed and ``run_id`` is ``None``.
    """
    # Tasks 1-3 live in their own modules. Imported here (not at module load) so
    # they can share this module's browser primitives without an import cycle.
    from src.tools.linkedin_best_matching_resume import read_job_description
    from src.tools.linkedin_job_selection import _task2_ok, _task2_on_page
    from src.tools.linkedin_search import _task1_ok, _task1_on_page

    settings = settings or load_settings()
    notify = progress or (lambda _message: None)
    session = build_browser(settings)
    task1 = Task1Outcome(start_url=url, search_query=search_query)
    task2 = Task2Outcome()
    job_description = JobDescription()
    run_id: str | None = None
    await session.start()
    try:
        page = await session.new_page()

        task1 = await _task1_on_page(page, url, search_query, settings, notify)
        if not _task1_ok(task1):
            notify("Task 1 did not complete; skipping Tasks 2-4.")
            task2.notes = "Task 1 did not complete; Tasks 2-4 were skipped."
            task1.screenshot_path = await capture_failure_screenshot(session, settings, "task1")
        else:
            task2 = await _task2_on_page(page, settings, notify, capture=read_job_description)
            if not _task2_ok(task2):
                task2.screenshot_path = await capture_failure_screenshot(session, settings, "task2")
            else:
                # Task 2 read the description while the job was open (before Easy
                # Apply); only re-read if that produced nothing.
                job_description = task2.job_description or JobDescription()
                if not job_description.is_read:
                    job_description = await read_job_description(page)
                notify(
                    "Task 3: read job description "
                    f"(title={job_description.title or '(untitled)'!r}, "
                    f"{len(job_description.body)} description chars)."
                )
                run_id = uuid4().hex
                _ACTIVE_RUNS[run_id] = _Run(session=session, page=page)
        return AgentOutcome(task1=task1, task2=task2, job_description=job_description), run_id
    finally:
        if run_id is None:
            with contextlib.suppress(Exception):
                await session.kill()


def get_run(run_id: str | None) -> _Run | None:
    """Return the registered live session for ``run_id``, if any."""
    return _ACTIVE_RUNS.get(run_id) if run_id else None


async def close_run(run_id: str | None) -> None:
    """Kill and forget the session registered under ``run_id`` (idempotent)."""
    if not run_id:
        return
    run = _ACTIVE_RUNS.pop(run_id, None)
    if run is None:
        return
    with contextlib.suppress(Exception):
        await run.session.kill()


def forget_run(run_id: str | None) -> None:
    """Forget a run whose browser is already gone (no kill attempt).

    Used when a live CDP connection drops (the human closed the window): there is
    nothing to kill, so the run is simply removed from the registry.
    """
    if run_id:
        _ACTIVE_RUNS.pop(run_id, None)


def run_is_connected(run_id: str | None) -> bool:
    """True while the run's browser still has a live CDP connection.

    A missing run is treated as not connected; a session that does not expose
    ``is_cdp_connected`` is treated as still alive, so the caller never closes a
    window it cannot confirm is gone.
    """
    run = get_run(run_id)
    if run is None:
        return False
    return bool(getattr(run.session, "is_cdp_connected", True))


async def wait_for_human_close(
    run_id: str | None,
    settings: Settings | None = None,
    progress=None,
) -> bool:
    """Leave the run's browser open and wait for the human to close it.

    Used when Task 4 stops at the terminal step (only **Submit application**
    remains): the window stays open so the human can review and submit the
    application manually, then closes it. Returns ``True`` once the browser is
    gone (closed by the human), or ``False`` when the wait times out — the
    session is then closed for them. ``AUTOJOB_SESSION_KEEP_OPEN_TIMEOUT_SECONDS``
    of ``0`` waits indefinitely.
    """
    settings = settings or load_settings()
    notify = progress or (lambda _message: None)
    run = get_run(run_id)
    if run is None:
        return True

    timeout = settings.session.keep_open_timeout_seconds
    poll = settings.session.keep_open_poll_seconds
    notify(
        "Task 4: reached the last step; leaving the browser open. Review and "
        "submit the application yourself, then close the browser window to "
        "finish the run."
    )
    deadline = None if timeout <= 0 else time.monotonic() + timeout
    while True:
        if not run_is_connected(run_id):
            forget_run(run_id)
            return True
        if deadline is not None and time.monotonic() >= deadline:
            notify("Task 4: browser still open after the wait; closing it.")
            await close_run(run_id)
            return False
        await asyncio.sleep(poll)


async def release_run(
    run_id: str | None,
    task4: Task4Outcome | None = None,
    settings: Settings | None = None,
    progress=None,
) -> str:
    """Release the run's browser, respecting the human's final Submit step.

    When Task 4 stopped at the terminal step (only **Submit application** remains)
    the window is left open and this waits for the human to close it (see
    :func:`wait_for_human_close`). On every other path the session is closed.
    Returns ``"human"`` (closed by the human), ``"timeout"`` (wait timed out and
    the session was closed), or ``"closed"`` (closed by the agent).
    """
    if task4 is not None and task4.awaiting_human_submit:
        return "human" if await wait_for_human_close(run_id, settings, progress) else "timeout"
    await close_run(run_id)
    return "closed"


async def fill_application(
    run_id: str | None,
    resume_path: str | None,
    settings: Settings | None = None,
    progress=None,
) -> tuple[Task4Outcome, Task5Outcome]:
    """Fill the open Easy Apply form in the session registered under ``run_id``.

    Returns ``(task4, task5)``. The session is left open; the caller closes it (the
    graph's ``cleanup`` node or :func:`run_full_agent`), so an in-flight session
    can still be screenshotted on failure.
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
        run.page, run.session, resume_path, answers, settings, notify, human=human
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
    skipped when the previous one fails. The session is closed at the end.
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

    When Task 4 reaches the terminal step (only **Submit application** remains)
    the browser is left open and the call waits for the human to close it (see
    :func:`release_run`); otherwise the session is closed at the end. This is the
    one-shot helper used by the live integration test; the Task 8 submit-and-repeat
    loop lives in the graph (see :mod:`src.nodes.apply_loop`).
    """
    from src.tools.linkedin_best_matching_resume import ensure_resume  # keep light

    settings = settings or load_settings()
    outcome, run_id = await start_tasks(url, search_query, settings, progress)
    if run_id is None:
        return outcome
    try:
        run = get_run(run_id)
        outcome.task3 = await ensure_resume(
            outcome.job_description,
            settings.resumes_dir,
            settings,
            page=run.page if run is not None else None,
            notify=progress or (lambda _message: None),
        )
        if outcome.task3.selected_path:
            outcome.task4, outcome.task5 = await fill_application(
                run_id, outcome.task3.selected_path, settings, progress
            )
    finally:
        await release_run(run_id, outcome.task4, settings, progress)
    return outcome


# Task 1's LinkedIn job-search flow (login, search, the optional "Try AI job
# search" detour, and the Easy Apply filter) now lives in
# :mod:`src.tools.linkedin_search`. The names are re-exported lazily so existing
# callers and tests can keep importing them from this module. The re-export must
# be lazy: linkedin_search imports this module's shared primitives at load time,
# so importing it here at load time would create a cycle.
_TASK1_REEXPORTS = frozenset(
    {
        "_AI_CANDIDATES_QUERY",
        "_EASY_APPLY_FILTER_SELECTORS",
        "_FILTER_QUERY",
        "_JOBS_SEARCH_INPUT_SELECTORS",
        "_JOBS_SEARCH_SUBMIT_SELECTORS",
        "_JOBS_TAB_URL",
        "_LOGIN_STATE_QUERY",
        "_MAX_AI_JOB_SEARCH_CLICKS",
        "_task1_ok",
        "_task1_on_page",
        "click_ai_job_search",
        "easy_apply_filter_selected",
        "find_ai_job_search_button",
        "find_easy_apply_filter",
        "find_jobs_search_input",
        "is_logged_in",
        "open_jobs_search",
        "read_ai_job_search_candidates",
        "run_ai_job_search_detour",
        "run_task1",
        "select_easy_apply_filter",
        "type_jobs_search",
        "wait_for_ai_job_search_button",
        "wait_for_login",
    }
)

# Task 2's job-selection flow (read the job list, pick a job, click its Easy Apply
# button, and confirm the form opened) now lives in
# :mod:`src.tools.linkedin_job_selection`. Re-exported lazily for the same reason
# as Task 1: linkedin_job_selection imports this module's shared primitives at
# load time, so importing it here at load time would create a cycle.
_TASK2_REEXPORTS = frozenset(
    {
        "_APPLY_MODAL_QUERY",
        "_JOB_CARD_SELECTORS",
        "_JOB_DETAILS_APPLY_SELECTORS",
        "_element_is_job_card",
        "_first_line",
        "_task2_ok",
        "_task2_on_page",
        "find_job_apply_button",
        "read_apply_modal",
        "read_job_cards",
        "wait_for_easy_apply_modal",
        "wait_for_job_apply_button",
    }
)

# Task 3's flow (read the open job's description and pick the best-matching
# resume) now lives in :mod:`src.tools.linkedin_best_matching_resume`. Re-exported
# lazily for the same reason as Tasks 1-2: that module imports this module's
# shared primitives at load time, so importing it here would create a cycle.
_TASK3_REEXPORTS = frozenset(
    {
        "_JOB_DESCRIPTION_QUERY",
        "read_job_description",
    }
)

# Task 4's fill flow (enumerate the Easy Apply form, fill known fields, attach the
# resume, and advance steps without submitting) now lives in
# :mod:`src.tools.linkedin_easy_apply_fill`. Re-exported lazily for the same
# reason as Tasks 1-3: that module (via :mod:`src.tools.linkedin_ask_human`)
# imports this module's shared primitives at load time, so importing it here at
# load time would create a cycle.
_TASK4_REEXPORTS = frozenset(
    {
        "_ENUMERATE_FORM_QUERY",
        "_FILL_INPUT_JS",
        "_FILL_SELECT_JS",
        "_FORM_BUTTONS_QUERY",
        "_MAX_FORM_STEPS",
        "_RESUME_OPTIONS_QUERY",
        "_SELECT_PLACEHOLDERS",
        "_attach_resume",
        "_blocked_note",
        "_blocking_questions",
        "_choice_hint",
        "_control_already_answered",
        "_fill_field",
        "_fill_step",
        "_form_signature",
        "_resume_file_selector",
        "_resume_listed_names",
        "_select_value_for",
        "_task4_ok",
        "_task4_on_page",
        "enumerate_form_fields",
        "read_form",
        "read_form_buttons",
        "read_resume_info",
        "read_resume_options",
        "upload_file_via_cdp",
    }
)

# Task 5's ask-the-human flow (show a browser banner for an unknown question,
# read the answer the human types into the form, and remember it) now lives in
# :mod:`src.tools.linkedin_ask_human`. Re-exported lazily for the same reason as
# Tasks 1-4: that module imports this module's shared primitives at load time, so
# importing it here at load time would create a cycle.
_TASK5_REEXPORTS = frozenset(
    {
        "_HIDE_UNKNOWN_JS",
        "_READ_FORM_ANSWER_JS",
        "_READ_UNKNOWN_JS",
        "_SHOW_UNKNOWN_JS",
        "_WATCH_FORM_ANSWER_JS",
        "_remember_answer",
        "ask_human_for_answer",
    }
)


def __getattr__(name: str):
    """Re-export the moved Task 1-5 names from their modules."""
    if name in _TASK1_REEXPORTS:
        from src.tools import linkedin_search

        return getattr(linkedin_search, name)
    if name in _TASK2_REEXPORTS:
        from src.tools import linkedin_job_selection

        return getattr(linkedin_job_selection, name)
    if name in _TASK3_REEXPORTS:
        from src.tools import linkedin_best_matching_resume

        return getattr(linkedin_best_matching_resume, name)
    if name in _TASK4_REEXPORTS:
        from src.tools import linkedin_easy_apply_fill

        return getattr(linkedin_easy_apply_fill, name)
    if name in _TASK5_REEXPORTS:
        from src.tools import linkedin_ask_human

        return getattr(linkedin_ask_human, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
