"""browser-use wrapper for the LinkedIn agent (Tasks 1-4).

Task 1 launches a Chromium session, navigates to the LinkedIn login page, waits
for the user to log in (a human gate), then types the configured job query into
the jobs search bar and selects the **Easy Apply** filter on the results page.

Task 2 continues in the *same* session: it reads the job list left open by Task
1, opens the first job that offers Easy Apply (skipping external-apply jobs),
clicks its **Easy Apply** button, and confirms the application form opened.

Task 3 reads the open job's title, company, location, and description body from
the details pane so the offline resume selection can run.

Task 4 continues in the *same* session: it enumerates the open Easy Apply form,
fills every field whose answer is known, attaches the resume chosen by Task 3
(preferring a resume already listed on the form over uploading a duplicate), and
advances through multi-step forms — stopping before **Submit application**.

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
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from src.configuration import Settings, load_settings
from src.state import (
    AgentOutcome,
    FormField,
    JobDescription,
    Task1Outcome,
    Task2Outcome,
    Task4Outcome,
)
from src.tools.answers import load_answers, lookup_answer
from src.tools.forms import (
    answers_match,
    looks_like_resume_field,
    pick_listed_resume,
    pick_next_button,
)
from src.tools.linkedin import (
    build_jobs_search_url,
    is_logged_in_path,
    is_login_path,
    looks_like_apply_modal,
    looks_like_easy_apply_action,
    looks_like_jobs_search_input,
    pick_easy_apply_action_index,
    pick_easy_apply_filter_index,
    pick_easy_apply_index,
)

_INSTALL_HINT = (
    "browser-use is not installed. Enable the optional extra:\n"
    "  uv sync --extra browser\n"
    "  uvx playwright install chromium"
)

# LinkedIn renders the Easy Apply filter toggle with this aria-label; the phrase
# check below is a fallback for markup variants. The exact "Easy Apply" phrase
# is required so an unrelated "Apply" control is never matched.
_EASY_APPLY_FILTER_SELECTORS = (
    "button[aria-label*='Easy Apply']",
    "[role='button'][aria-label*='Easy Apply']",
)

# The jobs search bar on the Jobs tab: a keywords input plus a submit button.
_JOBS_TAB_URL = "https://www.linkedin.com/jobs/"
_JOBS_SEARCH_INPUT_SELECTORS = (
    "input.jobs-search-box__keyboard-text-input",
    "input[aria-label='Search by title, skill, or company']",
    "input[aria-label*='title, skill, or company']",
    "input[aria-label*='Search jobs']",
    "input[placeholder*='title, skill, or company']",
)
_JOBS_SEARCH_SUBMIT_SELECTORS = (
    "button.jobs-search-box__submit-button",
    "button[aria-label='Search']",
    "button[type='submit']",
)

# Job cards in the left-hand search-results list (Task 2).
_JOB_CARD_SELECTORS = (
    "li.jobs-search-results__list-item",
    "li.scaffold-layout__list-item",
    "div.job-card-container",
    "ul.jobs-search__results-list > li",
)

# The job's apply button in the right-hand details pane (Task 2). Its label is
# "Easy Apply" for Easy Apply jobs and "Apply" for external ones.
_JOB_DETAILS_APPLY_SELECTORS = (
    "div.jobs-search__job-details--container button.jobs-apply-button",
    "div.scaffold-layout__detail button.jobs-apply-button",
    "div.job-view-layout button.jobs-apply-button",
    "div.jobs-details button.jobs-apply-button",
    "button.jobs-apply-button",
)

# How long to keep waiting for the results list to render after a search.
_RESULTS_WAIT_SECONDS = 20.0
# Poll interval used while waiting for the details pane / apply modal.
_APPLY_POLL_SECONDS = 0.5

_LOGIN_STATE_QUERY = """
() => JSON.stringify({
  path: location.pathname,
  nav: !!document.querySelector('.global-nav, nav.global-nav, #global-nav'),
  loginForm: !!document.querySelector(
    'form.login__form, input#username, input[name="session_key"]'
  )
})
"""

_RESULTS_QUERY = """
() => JSON.stringify({
  count: document.querySelectorAll(
    'li.jobs-search-results__list-item, li.scaffold-layout__list-item, '
    + 'div.job-card-container, div.jobs-search-results-list__list-item, '
    + 'ul.jobs-search__results-list > li'
  ).length
})
"""

_FILTER_QUERY = """
() => JSON.stringify({
  selected: (() => {
    const btn = document.querySelector('[aria-label*="Easy Apply"]');
    const pressed = btn ? btn.getAttribute('aria-pressed') : null;
    const inUrl = (location.search || '').indexOf('f_AL=true') !== -1;
    return pressed === 'true' || inUrl;
  })()
})
"""

_APPLY_MODAL_QUERY = """
() => {
  const modal = document.querySelector(
    'div.jobs-easy-apply-modal, div[data-test-modal-container], '
    + 'div[role="dialog"].artdeco-modal, .artdeco-modal--layer-default'
  );
  return JSON.stringify({
    open: !!modal,
    text: modal ? (modal.innerText || '').slice(0, 1000) : ''
  });
}
"""

# The open job's details (Task 3): title, company, location, and description body.
_JOB_DESCRIPTION_QUERY = """
() => {
  const pick = (selectors) => {
    for (const selector of selectors) {
      const el = document.querySelector(selector);
      if (el && (el.innerText || '').trim()) return el.innerText.trim();
    }
    return '';
  };
  return JSON.stringify({
    title: pick([
      '.job-details-jobs-unified-top-card__job-title',
      '.jobs-unified-top-card__job-title',
      'h1.t-24', 'h1'
    ]),
    company: pick([
      '.job-details-jobs-unified-top-card__company-name',
      '.jobs-unified-top-card__company-name',
      'a.topcard__org-name-link'
    ]),
    location: pick([
      '.job-details-jobs-unified-top-card__bullet',
      '.jobs-unified-top-card__bullet',
      '.topcard__flavor--bullet'
    ]),
    body: pick([
      '.jobs-description__content',
      '.jobs-box__html-content',
      '#job-details',
      '.jobs-description'
    ]),
    url: location.href
  });
}
"""

# How many steps of a multi-step Easy Apply form to walk before stopping.
_MAX_FORM_STEPS = 6

# Enumerate the Easy Apply form's controls (Task 4). Each control gets a
# ``data-autojob-fill`` marker so it can be resolved back to a browser-use
# Element; radio/checkbox markers sit on the clickable label.
_ENUMERATE_FORM_QUERY = r"""
() => {
  const modal = document.querySelector(
    'div.jobs-easy-apply-modal, div[role="dialog"].artdeco-modal, '
    + '.artdeco-modal--layer-default, div[data-test-modal-container], .artdeco-modal'
  );
  if (!modal) return JSON.stringify({ open: false, fields: [] });

  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s;

  const ownLabel = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria && norm(aria)) return norm(aria);
    if (el.placeholder && norm(el.placeholder)) return norm(el.placeholder);
    if (el.id) {
      const l = modal.querySelector('label[for="' + esc(el.id) + '"]');
      if (l && norm(l.innerText)) return norm(l.innerText);
    }
    const wrap = el.closest('label');
    if (wrap && norm(wrap.innerText)) return norm(wrap.innerText);
    const box = el.closest(
      '.fb-dash-form-element, .artdeco-text-input, .jobs-easy-apply-form-element'
    );
    if (box) {
      const lab = box.querySelector(
        'label, .fb-dash-form-element__label, .artdeco-text-input--label'
      );
      if (lab && norm(lab.innerText)) return norm(lab.innerText);
    }
    return '';
  };

  const groupLabel = (el) => {
    const fs = el.closest('fieldset');
    if (fs) {
      const lg = fs.querySelector('legend');
      if (lg && norm(lg.innerText)) return norm(lg.innerText);
    }
    const box = el.closest(
      '.fb-dash-form-element, .jobs-easy-apply-form-element, .artdeco-form-element'
    );
    if (box) {
      const lab = box.querySelector('legend, .fb-dash-form-element__label, label');
      if (lab && norm(lab.innerText)) return norm(lab.innerText);
    }
    return '';
  };

  const clickTarget = (el) => {
    if (el.id) {
      const l = modal.querySelector('label[for="' + esc(el.id) + '"]');
      if (l) return l;
    }
    const wrap = el.closest('label');
    return wrap || el;
  };

  modal.querySelectorAll('[data-autojob-fill]').forEach(
    (el) => el.removeAttribute('data-autojob-fill')
  );

  const controls = modal.querySelectorAll(
    'input:not([type=hidden]):not([type=file]), textarea, select, '
    + '[role="radio"], [role="checkbox"]'
  );
  const fields = [];
  let i = 0;
  controls.forEach((el) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    let kind = 'input';
    if (tag === 'textarea') kind = 'textarea';
    else if (tag === 'select') kind = 'select';
    else if (role === 'radio' || type === 'radio') kind = 'radio';
    else if (role === 'checkbox' || type === 'checkbox') kind = 'checkbox';

    const isChoice = kind === 'radio' || kind === 'checkbox';
    const target = isChoice ? clickTarget(el) : el;
    if (!target.getClientRects().length) return; // skip controls on a hidden step
    const marker = 'f' + (i++);
    target.setAttribute('data-autojob-fill', marker);

    const options = [];
    if (tag === 'select') {
      Array.from(el.options).forEach((o) => options.push({ value: o.value, text: norm(o.text) }));
    }
    fields.push({
      marker: marker,
      kind: kind,
      type: type || tag,
      name: el.getAttribute('name') || '',
      question: isChoice ? (groupLabel(el) || ownLabel(el)) : ownLabel(el),
      option: isChoice ? ownLabel(el) : '',
      required: !!el.required || el.getAttribute('aria-required') === 'true',
      checked: !!el.checked || el.getAttribute('aria-checked') === 'true',
      value: norm(el.value || ''),
      options: options
    });
  });
  return JSON.stringify({ open: true, fields: fields });
}
"""

# Find the resume options already listed on the form plus any file input (Task 4).
_RESUME_OPTIONS_QUERY = r"""
() => {
  const modal = document.querySelector(
    'div.jobs-easy-apply-modal, div[role="dialog"].artdeco-modal, '
    + '.artdeco-modal--layer-default, div[data-test-modal-container], .artdeco-modal'
  );
  if (!modal) return JSON.stringify({ options: [], fileInput: false });

  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s;
  const ownLabel = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria && norm(aria)) return norm(aria);
    if (el.id) {
      const l = modal.querySelector('label[for="' + esc(el.id) + '"]');
      if (l && norm(l.innerText)) return norm(l.innerText);
    }
    const wrap = el.closest('label');
    if (wrap && norm(wrap.innerText)) return norm(wrap.innerText);
    return '';
  };
  const clickTarget = (el) => {
    if (el.id) {
      const l = modal.querySelector('label[for="' + esc(el.id) + '"]');
      if (l) return l;
    }
    const wrap = el.closest('label');
    return wrap || el;
  };

  modal.querySelectorAll('[data-autojob-resume]').forEach(
    (el) => el.removeAttribute('data-autojob-resume')
  );

  const options = [];
  let i = 0;
  modal.querySelectorAll('input[type="radio"], [role="radio"]').forEach((el) => {
    const text = ownLabel(el);
    const hay = (text + ' ' + (el.value || '') + ' ' + (el.name || '') + ' ' + (el.id || ''))
      .toLowerCase();
    if (/\.(pdf|docx|txt|md)\b/.test(text.toLowerCase()) || hay.includes('resume')) {
      const target = clickTarget(el);
      if (!target.getClientRects().length) return; // skip hidden steps
      const marker = 'r' + (i++);
      target.setAttribute('data-autojob-resume', marker);
      options.push({
        marker: marker,
        label: text,
        value: el.value || '',
        checked: !!el.checked || el.getAttribute('aria-checked') === 'true'
      });
    }
  });

  const file = modal.querySelector('input[type="file"]');
  if (file) file.setAttribute('data-autojob-file', '1');
  return JSON.stringify({ options: options, fileInput: !!file });
}
"""

# List the modal's buttons so the agent can advance a form (never submit).
_FORM_BUTTONS_QUERY = r"""
() => {
  const modal = document.querySelector(
    'div.jobs-easy-apply-modal, div[role="dialog"].artdeco-modal, '
    + '.artdeco-modal--layer-default, div[data-test-modal-container], .artdeco-modal'
  );
  if (!modal) return JSON.stringify({ buttons: [] });

  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  modal.querySelectorAll('[data-autojob-btn]').forEach(
    (el) => el.removeAttribute('data-autojob-btn')
  );

  const buttons = [];
  let i = 0;
  modal.querySelectorAll('footer button, .artdeco-modal__actionbar button, button').forEach(
    (el) => {
      if (!el.getClientRects().length) return; // skip buttons from a hidden step
      const text = norm(el.innerText) || norm(el.getAttribute('aria-label'));
      if (!text) return;
      const marker = 'b' + (i++);
      el.setAttribute('data-autojob-btn', marker);
      buttons.push({ marker: marker, text: text, disabled: !!el.disabled });
    }
  );
  return JSON.stringify({ buttons: buttons });
}
"""

# Set a text/textarea value the way React expects (native setter + events).
_FILL_INPUT_JS = r"""
(value) => {
  const proto = this.tagName === 'TEXTAREA'
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(this, value);
  this.dispatchEvent(new Event('input', { bubbles: true }));
  this.dispatchEvent(new Event('change', { bubbles: true }));
  return this.value;
}
"""

# Set a <select> value and fire the change event.
_FILL_SELECT_JS = r"""
(value) => {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
  setter.call(this, value);
  this.dispatchEvent(new Event('change', { bubbles: true }));
  return this.value;
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


def _first_line(text: str) -> str:
    """First non-empty line of ``text`` (a job card's title), truncated."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:200]
    return ""


def build_browser(settings: Settings):
    """Build a Chromium session that persists logins in ``data/profile``."""
    Browser = _require_browser_use()
    settings.profile_dir.mkdir(parents=True, exist_ok=True)
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


async def find_jobs_search_input(page):
    """Return the jobs search bar's keywords input, or ``None`` when absent."""
    field = await _first_element(page, _JOBS_SEARCH_INPUT_SELECTORS)
    if field is not None:
        return field

    # Fall back to scanning every input and matching its label/placeholder.
    for element in await _query_elements(page, "input"):
        if looks_like_jobs_search_input(await _element_label(element)):
            return element
    return None


async def type_jobs_search(page, query: str, settings: Settings) -> bool:
    """Open the Jobs tab, type ``query`` into the search bar, and submit it."""
    await page.goto(_JOBS_TAB_URL)
    await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)
    await _pace(settings)

    field = await find_jobs_search_input(page)
    if field is None:
        return False

    await _safe(field.evaluate("() => this.scrollIntoView({block: 'center'})"))
    try:
        await field.fill(query)
    except Exception:  # noqa: BLE001 - fall back to URL-based search
        return False
    await _pace(settings)

    submit = await _first_element(page, _JOBS_SEARCH_SUBMIT_SELECTORS)
    if submit is not None:
        await _safe(submit.click())
    else:
        # The field is still focused from fill(); Enter submits the search.
        await _safe(page.press("Enter"))
    await _pace(settings)
    return True


async def is_logged_in(page) -> bool:
    """True when the current page indicates an authenticated session."""
    payload = _loads(await _safe(page.evaluate(_LOGIN_STATE_QUERY), ""))
    path = payload.get("path") or ""
    if is_logged_in_path(path):
        return True
    if is_login_path(path):
        return False
    # Ambiguous page (e.g. root): fall back to the global nav / login form.
    return bool(payload.get("nav")) and not payload.get("loginForm")


async def wait_for_login(page, *, timeout_seconds: float, poll_seconds: float) -> bool:
    """Poll until the user has logged in, or the timeout elapses."""
    if await is_logged_in(page):
        return True
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        await asyncio.sleep(poll_seconds)
        if await is_logged_in(page):
            return True
    return False


async def results_count(page) -> int:
    """Number of job cards currently rendered on the search results page."""
    payload = _loads(await _safe(page.evaluate(_RESULTS_QUERY), ""))
    try:
        return int(payload.get("count") or 0)
    except (TypeError, ValueError):
        return 0


async def open_jobs_search(page, query: str, settings: Settings) -> tuple[bool, int, str]:
    """Type ``query`` into the jobs search bar and submit; return results info.

    Returns ``(found, count, url)``. If the search bar cannot be found, it falls
    back to navigating to the equivalent search URL so the run can still proceed.
    """
    typed = await type_jobs_search(page, query, settings)
    if not typed:
        await page.goto(build_jobs_search_url(query))
        await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)

    count = await results_count(page)
    deadline = time.monotonic() + _RESULTS_WAIT_SECONDS
    while count == 0 and time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        count = await results_count(page)

    current_url = await _safe(page.get_url(), "") or ""
    return count > 0, count, current_url


async def find_easy_apply_filter(page):
    """Return the Easy Apply *filter* control, or ``None`` when absent."""
    candidates: list = []
    for selector in _EASY_APPLY_FILTER_SELECTORS:
        candidates.extend(await _query_elements(page, selector))

    labels = [await _element_label(element) for element in candidates]
    # Prefer a control whose label mentions "filter" so a job's Easy Apply
    # *button* (also matching ``*='Easy Apply'``) is not mistaken for the filter.
    index = pick_easy_apply_filter_index(labels)
    if index is None:
        index = pick_easy_apply_index(labels)
    if index is not None:
        return candidates[index]

    # Fall back to scanning every interactive control on the page.
    controls = await _query_elements(page, "button, [role='button']")
    labels = [await _element_label(element) for element in controls]
    index = pick_easy_apply_filter_index(labels)
    if index is None:
        index = pick_easy_apply_index(labels)
    return controls[index] if index is not None else None


async def easy_apply_filter_selected(page) -> bool:
    """True when the Easy Apply filter is active on the results page."""
    payload = _loads(await _safe(page.evaluate(_FILTER_QUERY), ""))
    return bool(payload.get("selected"))


async def select_easy_apply_filter(page, settings: Settings) -> tuple[bool, str]:
    """Click the Easy Apply filter; return ``(selected, note)``."""
    note = ""
    button = await find_easy_apply_filter(page)
    if button is not None:
        await _safe(button.evaluate("() => this.scrollIntoView({block: 'center'})"))
        await _pace(settings)
        try:
            await button.click()
        except Exception as exc:  # noqa: BLE001 - fall through to the URL toggle
            note = f"Easy Apply filter click failed: {exc}"
        if settings.session.post_click_wait_seconds:
            await asyncio.sleep(settings.session.post_click_wait_seconds)

    if await easy_apply_filter_selected(page):
        return True, note

    # Fallback: the same toggle is exposed as the f_AL=true query parameter.
    current = await _safe(page.get_url(), "") or ""
    if current and "f_AL=true" not in current:
        separator = "&" if "?" in current else "?"
        await page.goto(f"{current}{separator}f_AL=true")
        await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)
        if await easy_apply_filter_selected(page):
            return True, note

    return False, note or "Easy Apply filter could not be selected"


async def read_job_cards(page) -> list:
    """Return the job cards currently shown in the search results list."""
    for selector in _JOB_CARD_SELECTORS:
        cards = await _query_elements(page, selector)
        if cards:
            return cards
    return []


async def find_job_apply_button(page) -> tuple:
    """Return ``(element, label)`` for the details pane's apply button, or ``(None, "")``."""
    button = await _first_element(page, _JOB_DETAILS_APPLY_SELECTORS)
    if button is not None:
        return button, await _element_label(button)

    # Fall back to scanning interactive controls for an Easy Apply *action*
    # (an Easy Apply label that is not the results filter).
    controls = await _query_elements(page, "button, [role='button']")
    labels = [await _element_label(element) for element in controls]
    index = pick_easy_apply_action_index(labels)
    return (controls[index], labels[index]) if index is not None else (None, "")


async def wait_for_job_apply_button(page, settings: Settings) -> tuple:
    """Wait for the details pane's apply button to appear; return ``(element, label)``."""
    deadline = time.monotonic() + settings.session.easy_apply_timeout_seconds
    button, label = await find_job_apply_button(page)
    while button is None and time.monotonic() < deadline:
        await asyncio.sleep(_APPLY_POLL_SECONDS)
        button, label = await find_job_apply_button(page)
    return button, label


async def read_apply_modal(page) -> tuple[bool, str]:
    """Return ``(open, text)`` for the Easy Apply application form/modal."""
    payload = _loads(await _safe(page.evaluate(_APPLY_MODAL_QUERY), ""))
    if not payload.get("open"):
        return False, ""
    text = payload.get("text") or ""
    # An unrelated dialog should not count; require recognisable Easy Apply text
    # when the modal exposes any.
    return (not text or looks_like_apply_modal(text)), text


async def wait_for_easy_apply_modal(page, settings: Settings) -> tuple[bool, str]:
    """Wait for the Easy Apply application form to open; return ``(open, text)``."""
    deadline = time.monotonic() + settings.session.easy_apply_timeout_seconds
    opened, text = await read_apply_modal(page)
    while not opened and time.monotonic() < deadline:
        await asyncio.sleep(_APPLY_POLL_SECONDS)
        opened, text = await read_apply_modal(page)
    return opened, text


async def read_job_description(page) -> JobDescription:
    """Read the open job's title, company, location, and description (Task 3)."""
    payload = _loads(await _safe(page.evaluate(_JOB_DESCRIPTION_QUERY), ""))
    return JobDescription(
        title=(payload.get("title") or "").strip(),
        company=(payload.get("company") or "").strip(),
        location=(payload.get("location") or "").strip(),
        body=(payload.get("body") or "").strip(),
        page_url=payload.get("url") or None,
    )


def _append_note(existing: str, extra: str) -> str:
    return f"{existing}; {extra}" if existing else extra


async def enumerate_form_fields(page) -> tuple[bool, list[dict]]:
    """Return ``(form_open, fields)`` for the open Easy Apply form (Task 4)."""
    payload = _loads(await _safe(page.evaluate(_ENUMERATE_FORM_QUERY), ""))
    return bool(payload.get("open")), list(payload.get("fields") or [])


async def read_resume_options(page) -> tuple[list[dict], bool]:
    """Return ``(listed_resume_options, file_input_present)`` for the form (Task 4)."""
    payload = _loads(await _safe(page.evaluate(_RESUME_OPTIONS_QUERY), ""))
    return list(payload.get("options") or []), bool(payload.get("fileInput"))


async def read_form_buttons(page) -> list[dict]:
    """Return the Easy Apply modal's buttons (Task 4)."""
    payload = _loads(await _safe(page.evaluate(_FORM_BUTTONS_QUERY), ""))
    return list(payload.get("buttons") or [])


async def _marker_element(page, attribute: str, marker: str):
    return await _first_element(page, [f'[{attribute}="{marker}"]'])


async def _fill_field(element, field: dict, answer: str) -> tuple[bool, str]:
    """Fill one known field with the right control action; return ``(ok, error)``."""
    kind = field.get("kind")
    try:
        await _safe(element.evaluate("() => this.scrollIntoView({block: 'center'})"))
        if kind == "select":
            await element.evaluate(_FILL_SELECT_JS, str(answer))
        elif kind == "checkbox":
            if str(answer).strip().lower() in {"yes", "true", "1", "on"}:
                await element.check()
        elif kind == "radio":
            await element.click()
        else:
            await element.evaluate(_FILL_INPUT_JS, str(answer))
        return True, ""
    except Exception as exc:  # noqa: BLE001 - one bad field must not stop the run
        return False, f"{type(exc).__name__}: {exc}"


async def _fill_step(
    page, fields: list[dict], answers: dict[str, str], settings: Settings
) -> tuple[int, int, list[str], list[FormField]]:
    """Fill the known fields of one form step; leave the rest unknown."""
    known = filled = 0
    unknown: list[str] = []
    records: list[FormField] = []

    radio_groups: dict[str, list[dict]] = {}
    others: list[dict] = []
    for field in fields:
        if field.get("kind") == "radio":
            key = field.get("name") or field.get("question") or field.get("marker")
            radio_groups.setdefault(key, []).append(field)
        else:
            others.append(field)

    async def _apply(record: FormField, field: dict, answer: str) -> None:
        nonlocal known, filled
        record.known = True
        record.value = answer
        element = await _marker_element(page, "data-autojob-fill", field["marker"])
        if element is None:
            record.error = "field element not found"
        else:
            ok, error = await _fill_field(element, field, answer)
            record.filled = ok
            record.error = error
        known += 1
        filled += 1 if record.filled else 0
        records.append(record)

    for key, group in radio_groups.items():
        question = next((g.get("question") for g in group if g.get("question")), "") or key
        options = [g.get("option", "") for g in group if g.get("option")]
        if looks_like_resume_field(question, options):
            continue  # the resume control is handled by _attach_resume
        record = FormField(
            question=question,
            field_type="radio",
            name=key,
            required=any(g.get("required") for g in group),
            options=options,
        )
        found = lookup_answer(answers, [question, key])
        if found is None:
            unknown.append(question)
            records.append(record)
            continue
        _, answer = found
        option = next((g for g in group if answers_match(g.get("option", ""), answer)), None)
        if option is None:
            record.known = True
            record.value = answer
            record.error = "no option matched the stored answer"
            known += 1
            records.append(record)
            continue
        await _apply(record, option, answer)

    for field in others:
        question = field.get("question") or field.get("name") or f"field {field.get('marker')}"
        record = FormField(
            question=question,
            option=field.get("option", ""),
            field_type=field.get("type", ""),
            name=field.get("name", ""),
            required=bool(field.get("required")),
            options=[option.get("text", "") for option in field.get("options", [])],
        )
        found = lookup_answer(answers, [question, field.get("name", "")])
        if found is None:
            unknown.append(question)
            records.append(record)
            continue
        _, answer = found
        if field.get("kind") == "checkbox" and str(answer).strip().lower() in {
            "no",
            "false",
            "0",
            "off",
        }:
            record.known = True
            record.value = answer
            record.filled = True
            known += 1
            filled += 1
            records.append(record)
            continue
        await _apply(record, field, answer)

    await _pace(settings)
    return known, filled, unknown, records


async def upload_file_via_cdp(session, page, selector: str, file_path: str) -> None:
    """Attach ``file_path`` to the file input matching ``selector`` over CDP.

    Uses the page's own CDP session (``page.session_id``) so the element is
    resolved in the tab we are driving, and ``Runtime.evaluate`` to obtain the
    element's object id for ``DOM.setFileInputFiles``.
    """
    if not Path(file_path).is_file():
        raise RuntimeError(f"resume file does not exist: {file_path}")
    client = session.cdp_client
    session_id = await page.session_id
    await client.send.DOM.enable(session_id=session_id)
    expression = f"document.querySelector({json.dumps(selector)})"
    found = await client.send.Runtime.evaluate(
        params={"expression": expression, "returnByValue": False}, session_id=session_id
    )
    object_id = (found.get("result") or {}).get("objectId")
    if not object_id:
        raise RuntimeError(f"file input not found: {selector}")
    await client.send.DOM.setFileInputFiles(
        params={"files": [file_path], "objectId": object_id}, session_id=session_id
    )


async def _attach_resume(
    page,
    session,
    resume_path: str,
    settings: Settings,
    outcome: Task4Outcome,
    notify,
) -> None:
    """Attach the Task 3 resume: prefer a listed match, else upload (Task 4)."""
    options, _file_input = await read_resume_options(page)
    matched = pick_listed_resume(resume_path, [option.get("label", "") for option in options])

    if matched:
        option = next((o for o in options if o.get("label") == matched), None)
        element = (
            await _marker_element(page, "data-autojob-resume", option["marker"])
            if option is not None
            else None
        )
        if element is not None:
            await _safe(element.click())
            if settings.session.post_click_wait_seconds:
                await asyncio.sleep(settings.session.post_click_wait_seconds)
            outcome.resume_attached = True
            outcome.resume_selection = "listed"
            outcome.resume_listed_name = matched
            notify(f"Task 4: selected the listed resume {matched!r}.")
            return

    if await _first_element(page, ['[data-autojob-file="1"]']) is not None:
        selector = '[data-autojob-file="1"]'
    elif await _first_element(page, ['input[type="file"]']) is not None:
        selector = 'input[type="file"]'
    else:
        outcome.notes = _append_note(outcome.notes, "no resume control found on the form")
        return

    outcome.upload_attempted = True
    try:
        await upload_file_via_cdp(session, page, selector, resume_path)
    except Exception as exc:  # noqa: BLE001 - report and continue
        outcome.notes = _append_note(outcome.notes, f"resume upload failed: {exc}")
        return
    if settings.session.post_click_wait_seconds:
        await asyncio.sleep(settings.session.post_click_wait_seconds)
    outcome.resume_attached = True
    outcome.resume_selection = "uploaded"
    notify(f"Task 4: uploaded resume {Path(resume_path).name!r}.")


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


async def _task1_on_page(
    page,
    url: str,
    search_query: str,
    settings: Settings,
    notify,
) -> Task1Outcome:
    """Run Task 1 steps on an already-open page (no session lifecycle)."""
    outcome = Task1Outcome(start_url=url, search_query=search_query)
    await page.goto(url)
    await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)
    await _pace(settings)

    outcome.already_logged_in = await is_logged_in(page)
    if outcome.already_logged_in:
        notify("Already logged in to LinkedIn.")
        outcome.logged_in = True
    else:
        notify(
            "Not logged in yet - please log in using the browser window. "
            f"Waiting up to {settings.session.login_timeout_seconds}s ..."
        )
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
        found, count, search_url = await open_jobs_search(page, search_query, settings)
        await _pace(settings)
        outcome.results_found = found
        outcome.results_count = count
        outcome.search_url = search_url
        if found:
            selected, note = await select_easy_apply_filter(page, settings)
            outcome.easy_apply_filter_selected = selected
            outcome.notes = note

    outcome.page_url = await _safe(page.get_url(), None)
    outcome.page_title = await _safe(page.get_title(), "") or ""
    return outcome


async def _task2_on_page(page, settings: Settings, notify) -> Task2Outcome:
    """Run Task 2 steps on the results page left open by Task 1."""
    outcome = Task2Outcome()

    cards = await read_job_cards(page)
    deadline = time.monotonic() + _RESULTS_WAIT_SECONDS
    while not cards and time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        cards = await read_job_cards(page)
    outcome.jobs_seen = len(cards) or await results_count(page)
    notify(f"Task 2: {outcome.jobs_seen} job(s) in the list.")
    await _pace(settings)

    for index, card in enumerate(cards):
        title = _first_line(await _element_label(card))
        outcome.job_index = index
        outcome.job_title = title
        notify(f"Task 2: opening job {index + 1}: {title or '(untitled)'}")

        await _safe(card.evaluate("() => this.scrollIntoView({block: 'center'})"))
        try:
            await card.click()
        except Exception as exc:  # noqa: BLE001 - try the next job
            outcome.notes = f"Could not open job {index + 1}: {exc}"
            outcome.skipped_jobs += 1
            continue
        if settings.session.post_click_wait_seconds:
            await asyncio.sleep(settings.session.post_click_wait_seconds)
        await _pace(settings)

        button, label = await wait_for_job_apply_button(page, settings)
        if button is None or not looks_like_easy_apply_action(label):
            outcome.skipped_jobs += 1
            notify("Task 2: no Easy Apply for this job; skipping.")
            continue

        outcome.easy_apply_button_found = True
        await _safe(button.evaluate("() => this.scrollIntoView({block: 'center'})"))
        await _pace(settings)
        try:
            await button.click()
        except Exception as exc:  # noqa: BLE001 - try the next job
            outcome.notes = f"Easy Apply click failed: {exc}"
            continue
        outcome.easy_apply_clicked = True
        await _pace(settings)

        opened, modal_text = await wait_for_easy_apply_modal(page, settings)
        outcome.application_form_opened = opened
        outcome.modal_text = modal_text
        if opened:
            notify("Task 2: Easy Apply application form opened.")
            break
        outcome.notes = "Easy Apply form did not open after the click"

    outcome.page_url = await _safe(page.get_url(), None)
    outcome.page_title = await _safe(page.get_title(), "") or ""
    return outcome


async def _task4_on_page(
    page,
    session,
    resume_path: str | None,
    answers: dict[str, str],
    settings: Settings,
    notify,
) -> Task4Outcome:
    """Fill the open Easy Apply form and attach the resume, without submitting."""
    outcome = Task4Outcome(resume_path=resume_path or "")

    for step in range(_MAX_FORM_STEPS):
        opened, fields = await enumerate_form_fields(page)
        if not opened:
            if step == 0:
                outcome.notes = _append_note(outcome.notes, "Easy Apply form was not found")
            break

        outcome.form_open = True
        outcome.fields_enumerated += len(fields)
        known, filled, unknown, records = await _fill_step(page, fields, answers, settings)
        outcome.known_fields += known
        outcome.filled_fields += filled
        outcome.unknown_fields.extend(unknown)
        outcome.fields.extend(records)

        if resume_path and not outcome.resume_attached:
            await _attach_resume(page, session, resume_path, settings, outcome, notify)

        if step >= _MAX_FORM_STEPS - 1:
            break

        button = pick_next_button(await read_form_buttons(page))
        if button is None:
            break  # only a submit (never clicked) or nothing left to advance
        element = await _marker_element(page, "data-autojob-btn", button["marker"])
        if element is None:
            break
        notify(f"Task 4: advancing form step via {button.get('text')!r}.")
        await _safe(element.click())
        outcome.steps_advanced += 1
        if settings.session.post_click_wait_seconds:
            await asyncio.sleep(settings.session.post_click_wait_seconds)
        await _pace(settings)

    outcome.page_url = await _safe(page.get_url(), None)
    return outcome


def _task4_ok(outcome: Task4Outcome) -> bool:
    return bool(
        outcome.form_open
        and outcome.resume_attached
        and outcome.filled_fields == outcome.known_fields
        and not outcome.submitted
    )


def _task1_ok(outcome: Task1Outcome) -> bool:
    return bool(outcome.logged_in and outcome.results_found and outcome.easy_apply_filter_selected)


def _task2_ok(outcome: Task2Outcome) -> bool:
    return bool(outcome.easy_apply_clicked and outcome.application_form_opened)


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
        with contextlib.suppress(Exception):
            await session.kill()


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
) -> Task4Outcome:
    """Fill the open Easy Apply form in the session registered under ``run_id``.

    The session is left open; the caller closes it (the graph's ``cleanup`` node
    or :func:`run_full_agent`), so an in-flight session can still be screenshotted
    on failure.
    """
    settings = settings or load_settings()
    notify = progress or (lambda _message: None)
    run = get_run(run_id)
    if run is None:
        return Task4Outcome(
            resume_path=resume_path or "",
            notes="browser session is no longer available",
        )

    answers = load_answers(settings.answers_file)
    outcome = await _task4_on_page(run.page, run.session, resume_path, answers, settings, notify)
    if not _task4_ok(outcome):
        outcome.screenshot_path = await capture_failure_screenshot(run.session, settings, "task4")
    return outcome


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
    from src.tools.resumes import select_best_resume  # local import keeps this light

    settings = settings or load_settings()
    outcome, run_id = await start_tasks(url, search_query, settings, progress)
    if run_id is None:
        return outcome
    try:
        outcome.task3 = select_best_resume(outcome.job_description, settings.resumes_dir)
        if outcome.task3.selected_path:
            outcome.task4 = await fill_application(
                run_id, outcome.task3.selected_path, settings, progress
            )
    finally:
        await close_run(run_id)
    return outcome
