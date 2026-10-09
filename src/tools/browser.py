"""browser-use wrapper for the LinkedIn agent (Task 5).

Task 1 (log in, search "software engineer", click LinkedIn's optional "Try AI job
search", and select the **Easy Apply** filter) lives in
:mod:`src.tools.linkedin_search`; Task 2 (select a job from the results list and
open its **Easy Apply** form) lives in :mod:`src.tools.linkedin_job_selection`;
Task 3 (read the open job's description and pick the best-matching resume) lives in
:mod:`src.tools.linkedin_best_matching_resume`; Task 4 (enumerate the open Easy
Apply form, fill every field whose answer is known, attach the Task 3 resume, and
advance through multi-step forms — stopping before **Submit application**) lives in
:mod:`src.tools.linkedin_easy_apply_fill`.
This module owns the shared browser primitives plus Task 5. For back-compat the
moved names are still reachable here (see ``__getattr__`` below), so ``browser``
remains the stable entry point.

Task 5 rides along with Task 4: when a question is unknown, a visible browser
banner says the agent does not know the answer and the run pauses for the human
to type the answer into the form field itself. The answer is remembered in the
answer store so the same (normalized) question is filled automatically next time.

The interaction uses browser-use's deterministic CDP actor API (``Page`` /
``Element``); no LLM is involved.

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
from src.tools.answers import load_answers, normalize_question, save_answer

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


# Task 5: a visible banner that tells the human the agent cannot answer a
# question and asks them to type the answer into the form field itself. The
# question text is set via ``textContent`` so page content can never inject
# markup. The banner records its state in ``data-autojob-state`` (``pending`` /
# ``skipped``) so the agent can poll it without blocking the page. There is no
# input in the banner: the answer is read from the form control the human edits.
_SHOW_UNKNOWN_JS = r"""
(question, hint) => {
  let box = document.getElementById('autojob-unknown');
  if (!box) {
    box = document.createElement('div');
    box.id = 'autojob-unknown';
    box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-label', 'AutoJobApply needs an answer');
    box.style.cssText = [
      'position:fixed', 'right:24px', 'bottom:24px', 'z-index:2147483647',
      'max-width:420px', 'background:#ffffff', 'color:#1a1a1a',
      'border:2px solid #b24020', 'border-radius:8px',
      'box-shadow:0 8px 24px rgba(0,0,0,.35)', 'padding:16px',
      "font:14px/1.4 -apple-system,'Segoe UI',Roboto,Arial,sans-serif"
    ].join(';');
    const heading = document.createElement('div');
    heading.textContent = 'AutoJobApply does not know this answer';
    heading.style.cssText = 'font-weight:600;color:#b24020;margin-bottom:8px';
    const q = document.createElement('div');
    q.id = 'autojob-unknown-question';
    q.style.cssText = 'margin-bottom:8px';
    const hintEl = document.createElement('div');
    hintEl.id = 'autojob-unknown-hint';
    hintEl.style.cssText = 'margin-bottom:8px;color:#555;font-size:13px';
    const instruction = document.createElement('div');
    instruction.id = 'autojob-unknown-instruction';
    instruction.textContent =
      'Type your answer in the form field on the page, then click away to confirm.';
    instruction.style.cssText = 'margin-bottom:8px;color:#555;font-size:13px';
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:8px;justify-content:flex-end';
    const skip = document.createElement('button');
    skip.id = 'autojob-unknown-skip';
    skip.type = 'button';
    skip.textContent = 'Skip';
    skip.style.cssText = 'padding:6px 12px;border:1px solid #666;border-radius:4px;cursor:pointer';
    row.appendChild(skip);
    box.appendChild(heading);
    box.appendChild(q);
    box.appendChild(hintEl);
    box.appendChild(instruction);
    box.appendChild(row);
    document.body.appendChild(box);
    skip.addEventListener('click', () => box.setAttribute('data-autojob-state', 'skipped'));
  }
  box.setAttribute('data-autojob-state', 'pending');
  const q = document.getElementById('autojob-unknown-question');
  if (q) q.textContent = question || 'this question';
  const hintEl = document.getElementById('autojob-unknown-hint');
  if (hintEl) {
    hintEl.textContent = hint || '';
    hintEl.style.display = hint ? 'block' : 'none';
  }
  return true;
}
"""

# Task 5: watch the form for the human's answer. The banner has no input, so the
# human types into the actual form control; this records the edited value on the
# page and flags when the edit is finished (a change/blur or Enter). A single
# document-level listener is installed once and reset for each question, so the
# agent can poll the value without blocking.
_WATCH_FORM_ANSWER_JS = r"""
() => {
  const KEY = '__autojobFormAnswer';
  const previous = window[KEY];
  if (previous && previous.installed) {
    previous.value = '';
    previous.done = false;
    return true;
  }
  const state = { installed: true, value: '', done: false };
  window[KEY] = state;

  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s;

  const isControl = (el) => {
    if (!el || !el.tagName) return false;
    const tag = el.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
    const role = (el.getAttribute('role') || '').toLowerCase();
    return role === 'radio' || role === 'checkbox';
  };

  const labelText = (el) => {
    if (el.id) {
      const l = document.querySelector('label[for="' + esc(el.id) + '"]');
      if (l && norm(l.innerText)) return norm(l.innerText);
    }
    const wrap = el.closest('label');
    if (wrap && norm(wrap.innerText)) return norm(wrap.innerText);
    return '';
  };

  const readValue = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'select') {
      const opt = el.options ? el.options[el.selectedIndex] : null;
      return opt ? norm(opt.text || opt.value) : '';
    }
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (type === 'checkbox') return el.checked ? 'Yes' : '';
    if (type === 'radio') return el.checked ? (labelText(el) || norm(el.value)) : '';
    return norm(el.value);
  };

  const record = (el, finished) => {
    if (!isControl(el)) return;
    const value = readValue(el);
    if (!value) return;  // ignore empty edits and unrelated blur events
    state.value = value;
    if (finished) state.done = true;
  };

  document.addEventListener('input', (e) => record(e.target, false), true);
  document.addEventListener('change', (e) => record(e.target, true), true);
  document.addEventListener('focusout', (e) => record(e.target, true), true);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') record(e.target, true);
  }, true);
  return true;
}
"""

# Read the answer the human typed into the form (value + whether the edit is done).
_READ_FORM_ANSWER_JS = r"""
() => {
  const state = window.__autojobFormAnswer;
  if (!state) return JSON.stringify({ value: '', done: false });
  return JSON.stringify({ value: state.value || '', done: !!state.done });
}
"""

# Read the banner's current state (``pending`` / ``skipped``).
_READ_UNKNOWN_JS = r"""
() => {
  const box = document.getElementById('autojob-unknown');
  if (!box) return JSON.stringify({ present: false });
  return JSON.stringify({
    present: true,
    state: box.getAttribute('data-autojob-state') || 'pending'
  });
}
"""

# Remove the banner and reset the watcher once the question is resolved.
_HIDE_UNKNOWN_JS = r"""
() => {
  const box = document.getElementById('autojob-unknown');
  if (box) box.remove();
  const state = window.__autojobFormAnswer;
  if (state) {
    state.value = '';
    state.done = false;
  }
  return true;
}
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


async def ask_human_for_answer(
    page,
    question: str,
    field_type: str,
    hint: str,
    settings: Settings,
    notify,
    human: Task5Outcome | None = None,
) -> str | None:
    """Task 5: show a browser banner and read the human's answer from the form.

    Returns the answer the human typed into the form control, or ``None`` when the
    human skipped or the wait timed out. The run pauses here (polling the page)
    instead of guessing. The banner plainly states the agent does not know the
    answer and, for a choice field, lists the allowed options (``hint``). The
    banner has no input: the human edits the real form field and this reads it.
    """
    human = human if human is not None else Task5Outcome()
    human.enabled = True
    human.asked += 1
    await _safe(page.evaluate(_WATCH_FORM_ANSWER_JS))
    shown = await _safe(page.evaluate(_SHOW_UNKNOWN_JS, question, hint or ""))
    if not shown:
        human.timed_out += 1
        human.notes = _append_note(
            human.notes, f"could not show the answer banner for {question!r}"
        )
        return None

    kind = f" ({field_type})" if field_type else ""
    notify(
        f"Task 5: I do not know {question!r}{kind}; type the answer in the form "
        "field in the browser."
    )
    deadline = time.monotonic() + settings.session.ask_timeout_seconds
    while time.monotonic() < deadline:
        payload = _loads(await _safe(page.evaluate(_READ_UNKNOWN_JS), ""))
        if str(payload.get("state") or "") == "skipped":
            await _safe(page.evaluate(_HIDE_UNKNOWN_JS))
            human.skipped += 1
            notify(f"Task 5: you skipped {question!r}; leaving it unknown.")
            return None
        answer_payload = _loads(await _safe(page.evaluate(_READ_FORM_ANSWER_JS), ""))
        answer = str(answer_payload.get("value") or "").strip()
        if answer and answer_payload.get("done"):
            await _safe(page.evaluate(_HIDE_UNKNOWN_JS))
            human.answered += 1
            if question not in human.answered_questions:
                human.answered_questions.append(question)
            notify(f"Task 5: got an answer for {question!r} from the form.")
            return answer
        await asyncio.sleep(settings.session.ask_poll_seconds)

    await _safe(page.evaluate(_HIDE_UNKNOWN_JS))
    human.timed_out += 1
    human.notes = _append_note(
        human.notes, f"timed out waiting for an answer to {question!r}"
    )
    notify(f"Task 5: timed out waiting for an answer to {question!r}.")
    return None


def _remember_answer(
    settings: Settings,
    answers: dict[str, str],
    human: Task5Outcome | None,
    question: str,
    answer: str,
) -> None:
    """Persist a human answer and update the in-memory store for this run.

    An existing mapping is only replaced when the human supplies a new answer here;
    the update is recorded explicitly in the Task 5 notes rather than silently.
    """
    key = normalize_question(question)
    previous = answers.get(key)
    answers[key] = answer
    try:
        save_answer(settings.answers_file, question, answer)
    except OSError as exc:  # noqa: BLE001 - a failed write must not stop the fill
        if human is not None:
            human.notes = _append_note(human.notes, f"could not save {question!r}: {exc}")
        return
    if human is not None:
        action = "updated the stored answer" if previous and previous != answer else "remembered"
        human.notes = _append_note(human.notes, f"{action} the answer for {question!r}")


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
            task2 = await _task2_on_page(page, settings, notify)
            if not _task2_ok(task2):
                task2.screenshot_path = await capture_failure_screenshot(session, settings, "task2")
            else:
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
    """Run Tasks 1-4 end-to-end in one browser session (nothing is submitted)."""
    from src.tools.linkedin_best_matching_resume import select_best_resume  # keep light

    settings = settings or load_settings()
    outcome, run_id = await start_tasks(url, search_query, settings, progress)
    if run_id is None:
        return outcome
    try:
        outcome.task3 = select_best_resume(outcome.job_description, settings.resumes_dir)
        if outcome.task3.selected_path:
            outcome.task4, outcome.task5 = await fill_application(
                run_id, outcome.task3.selected_path, settings, progress
            )
    finally:
        await close_run(run_id)
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
# reason as Tasks 1-3: that module imports this module's shared primitives (and
# Task 5's ask-the-human helpers) at load time, so importing it here at load time
# would create a cycle.
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


def __getattr__(name: str):
    """Re-export the moved Task 1-4 names from their modules."""
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
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
