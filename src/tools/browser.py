"""browser-use wrapper for the LinkedIn agent (Tasks 1-5).

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
    FormField,
    JobDescription,
    Task1Outcome,
    Task2Outcome,
    Task4Outcome,
    Task5Outcome,
)
from src.tools.answers import load_answers, lookup_answer, normalize_question, save_answer
from src.tools.forms import (
    answers_match,
    looks_like_next,
    looks_like_resume_field,
    pick_listed_resume,
    pick_next_button,
)
from src.tools.linkedin import (
    build_jobs_search_url,
    card_is_applied,
    is_logged_in_path,
    is_login_path,
    looks_like_apply_modal,
    looks_like_easy_apply,
    looks_like_easy_apply_action,
    looks_like_job_card_label,
    looks_like_jobs_search_input,
    pick_ai_job_search_index,
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

# LinkedIn's optional "Try AI job search" entry point (Task 1). Its markup varies
# (it can be a button, a link, a role=button/role=link, or a tab) and its
# accessible name can differ from its visible text, so we scan interactive
# controls at runtime and combine every label source. Only controls that mention
# "search" are returned; the precise AI match is applied in Python.
_AI_CANDIDATES_QUERY = r"""
() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-autojob-ai]').forEach(
    (el) => el.removeAttribute('data-autojob-ai')
  );
  const controls = document.querySelectorAll(
    'button, a, [role="button"], [role="link"], [role="tab"], '
    + 'input[type="button"], input[type="submit"]'
  );
  const out = [];
  let i = 0;
  controls.forEach((el) => {
    const rects = el.getClientRects();
    if (!rects.length) return; // skip hidden controls
    const label = norm(
      (el.getAttribute('aria-label') || '') + ' '
      + (el.getAttribute('title') || '') + ' '
      + (el.innerText || '') + ' '
      + (el.value || '')
    );
    if (!label || (label.toLowerCase().indexOf('search') === -1
        && label.toLowerCase().indexOf('ai') === -1
        && label.toLowerCase().indexOf('artificial') === -1)) return;
    const marker = 'ai' + (i++);
    el.setAttribute('data-autojob-ai', marker);
    out.push({ marker: marker, label: label });
  });
  return JSON.stringify({ candidates: out });
}
"""


# The jobs search bar on the Jobs tab: a keywords input plus a submit button.
_JOBS_TAB_URL = "https://www.linkedin.com/jobs/"
_JOBS_SEARCH_INPUT_SELECTORS = (
    "input.jobs-search-box__keyboard-text-input",
    "input[aria-label='Search by title, skill, or company']",
    "input[aria-label*='title, skill, or company']",
    "input[aria-label*='Search jobs']",
    "input[placeholder*='title, skill, or company']",
    # LinkedIn's AI job search page prompt ("Describe the job you want").
    "input[aria-label*='Describe the job']",
    "input[placeholder*='Describe the job']",
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
    # AI/semantic results page (origin=SEMANTIC_SEARCH_LANDING_PAGE): the job
    # cards are rendered as div[role="button"], not classic <li> items. Their
    # accessible name starts with the job title and repeats it (see
    # _JOB_CARD_ATTR for the marker that proves a div is a job card).
    "[data-autojob-card]",
)

# Attribute used to mark AI/semantic job cards (div[role="button"]) so the
# classic selectors and CDP element resolution can find them.
_JOB_CARD_ATTR = "data-autojob-card"

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
# Safety cap on re-clicking "Try AI job search" when it reappears after each
# search, so a persistent control can never loop forever.
_MAX_AI_JOB_SEARCH_CLICKS = 3

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

_FILTER_QUERY = """
() => JSON.stringify({
  selected: (() => {
    const btn = document.querySelector(
      '[id="searchFilter_applyWithLinkedin"], [aria-label*="Easy Apply"]'
    );
    if (!btn) return (location.search || '').indexOf('f_AL=true') !== -1;
    // The real Easy Apply filter pill is role="radio" with aria-checked; other
    // variants expose aria-pressed. Neither is present on a job's apply button.
    const checked = btn.getAttribute('aria-checked');
    const pressed = btn.getAttribute('aria-pressed');
    const inUrl = (location.search || '').indexOf('f_AL=true') !== -1;
    return checked === 'true' || pressed === 'true' || inUrl;
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

# How many steps of a multi-step Easy Apply form to walk before stopping. The
# form is dynamic, so this is only a safety cap: the walk stops as soon as there
# is no Next button or the step stops changing.
_MAX_FORM_STEPS = 10

# Enumerate the Easy Apply form's controls (Task 4). Each control gets a
# ``data-autojob-fill`` marker so it can be resolved back to a browser-use
# Element; radio/checkbox markers sit on the clickable label.
_ENUMERATE_FORM_QUERY = r"""
() => {
  const modal = document.querySelector(
    'div.jobs-easy-apply-modal, div[role="dialog"].artdeco-modal, '
    + '.artdeco-modal--layer-default, div[data-test-modal-container], .artdeco-modal'
  );
  if (!modal) return JSON.stringify({ open: false, title: '', fields: [] });

  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const titleEl = modal.querySelector('h3');
  const title = titleEl ? norm(titleEl.innerText) : '';
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
      '.fb-dash-form-element, .fb-form-element, .fb-form-element-wrapper, '
      + '.artdeco-text-input, .jobs-easy-apply-form-element, '
      + '.jobs-easy-apply-form-section__grouping, .jobs-easy-apply-form-section'
    );
    if (box) {
      const lab = box.querySelector(
        'label, .fb-dash-form-element__label, .fb-form-element-label, '
        + '.artdeco-text-input--label'
      );
      if (lab && norm(lab.innerText)) return norm(lab.innerText);
    }
    // A choice control rendered as a styled div shows its own option label as
    // its text content (e.g. <div role="radio"><span>Yes</span></div>).
    const role = (el.getAttribute('role') || '').toLowerCase();
    if ((role === 'radio' || role === 'checkbox') && norm(el.innerText)) {
      return norm(el.innerText);
    }
    return '';
  };

  const groupLabel = (el) => {
    const fs = el.closest('fieldset');
    if (fs) {
      const lg = fs.querySelector('legend');
      if (lg && norm(lg.innerText)) return norm(lg.innerText);
    }
    // The question label usually sits in an outer grouping/section container
    // that also wraps the controls. Walk outward and take the first container
    // that actually holds a question label.
    const boxes = [
      '.jobs-easy-apply-form-section__grouping',
      '.jobs-easy-apply-form-section',
      '.fb-form-element-wrapper',
      '.fb-form-element',
      '.fb-dash-form-element',
      '.jobs-easy-apply-form-element',
      '.artdeco-form-element',
    ];
    for (const sel of boxes) {
      const box = el.closest(sel);
      if (!box) continue;
      const lab = box.querySelector(
        'legend, .fb-form-element-label, .fb-dash-form-element__label, label'
      );
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
  return JSON.stringify({ open: true, title: title, fields: fields });
}
"""

# Find the resume options already listed on the form plus any file input (Task 4).
# The resume control is dynamic: it may be a radio list, a ``<select>``, a file
# input, or an "Upload resume" button that reveals the file input only on click.
_RESUME_OPTIONS_QUERY = r"""
() => {
  const modal = document.querySelector(
    'div.jobs-easy-apply-modal, div[role="dialog"].artdeco-modal, '
    + '.artdeco-modal--layer-default, div[data-test-modal-container], .artdeco-modal'
  );
  if (!modal) {
    return JSON.stringify({
      options: [], fileInput: false, select: null, uploadButton: null
    });
  }

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
    const box = el.closest(
      '.fb-dash-form-element, .fb-form-element, .fb-form-element-wrapper, '
      + '.jobs-easy-apply-form-element, .jobs-easy-apply-form-section__grouping, '
      + '.jobs-easy-apply-form-section'
    );
    if (box) {
      const lab = box.querySelector(
        'label, .fb-dash-form-element__label, .fb-form-element-label'
      );
      if (lab && norm(lab.innerText)) return norm(lab.innerText);
    }
    const role = (el.getAttribute('role') || '').toLowerCase();
    if ((role === 'radio' || role === 'checkbox') && norm(el.innerText)) {
      return norm(el.innerText);
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

  ['data-autojob-resume', 'data-autojob-resume-select', 'data-autojob-resume-upload']
    .forEach((attr) => modal.querySelectorAll('[' + attr + ']').forEach(
      (el) => el.removeAttribute(attr)
    ));
  modal.querySelectorAll('[data-autojob-file]').forEach(
    (el) => el.removeAttribute('data-autojob-file')
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

  // A resume chooser rendered as a <select>.
  let select = null;
  modal.querySelectorAll('select').forEach((el) => {
    if (select) return;
    const label = ownLabel(el);
    const hay = (label + ' ' + (el.name || '') + ' ' + (el.id || '')).toLowerCase();
    const choices = Array.from(el.options).map(
      (o) => ({ value: o.value, text: norm(o.text) })
    );
    const looksLikeResume = hay.includes('resume')
      || choices.some((o) => /\.(pdf|docx|txt|md)\b/i.test(o.text));
    if (looksLikeResume && el.getClientRects().length) {
      const marker = 's' + (i++);
      el.setAttribute('data-autojob-resume-select', marker);
      select = { marker: marker, label: label, options: choices };
    }
  });

  const file = modal.querySelector('input[type="file"]');
  if (file) file.setAttribute('data-autojob-file', '1');

  // A button that reveals the file input (e.g. "Upload resume").
  let uploadButton = null;
  modal.querySelectorAll('button, [role="button"]').forEach((el) => {
    if (uploadButton) return;
    const text = norm(el.innerText) || norm(el.getAttribute('aria-label'));
    if (/upload|add resume|attach resume|choose file/i.test(text)
        && el.getClientRects().length) {
      const marker = 'u' + (i++);
      el.setAttribute('data-autojob-resume-upload', marker);
      uploadButton = { marker: marker, label: text };
    }
  });

  return JSON.stringify({
    options: options,
    fileInput: !!file,
    select: select,
    uploadButton: uploadButton
  });
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


def _first_line(text: str) -> str:
    """First non-empty line of ``text`` (a job card's title), truncated."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:200]
    return ""


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
    """Type ``query`` into the jobs search bar and submit it.

    When the jobs search bar is already on the page (e.g. after the first search)
    it is used as-is, like a real user typing. LinkedIn may reload or navigate as
    it normally does when a search is submitted. The Jobs tab is opened once when
    no search bar is present (e.g. when starting from the feed).
    """
    field = await find_jobs_search_input(page)
    if field is None:
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


async def open_jobs_search(page, query: str, settings: Settings) -> tuple[bool, int, str]:
    """Type ``query`` into the jobs search bar and submit; return results info.

    Returns ``(found, count, url)``. Searching behaves like LinkedIn's default:
    the page may reload or navigate. When the search bar cannot be found the run
    falls back to navigating to the equivalent search URL.
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
    """Return the Easy Apply *filter* toggle, or ``None`` when absent.

    The results page shows two controls whose accessible name contains "Easy
    Apply": the results filter pill (``id="searchFilter_applyWithLinkedin"``,
    ``role="radio"`` with ``aria-checked``, class ``search-reusables__filter-pill-button``
    — e.g. the pill beside "Backend" in the filter bar) and the blue "Easy Apply"
    apply button on a job (``jobs-apply-button`` / ``artdeco-button--primary``,
    blue background). They share the label text, so they are told apart by
    structure: the filter is a choice toggle (``role="radio"``/``aria-checked`` or
    ``aria-pressed``) and is never a ``jobs-apply-button``.

    A choice-toggle filter is always preferred; when there is no toggle, only a
    control whose label explicitly names the filter is accepted. When neither
    exists the caller falls back to the ``f_AL=true`` URL toggle, so a job's
    apply button is never clicked as if it were the filter.
    """
    candidates: list = []
    seen: set[int] = set()
    for selector in _EASY_APPLY_FILTER_SELECTORS + ("button, [role='button']",):
        for element in await _query_elements(page, selector):
            if id(element) in seen:
                continue
            seen.add(id(element))
            label = await _element_label(element)
            if looks_like_easy_apply(label) and not await _element_is_apply_button(element):
                candidates.append((element, label))

    if not candidates:
        return None

    # The filter pill is a choice toggle; the blue apply button is not.
    toggles = [
        (el, label) for el, label in candidates if await _element_is_choice_control(el)
    ]
    if toggles:
        labels = [label for _el, label in toggles]
        index = pick_easy_apply_filter_index(labels)
        if index is None:
            index = pick_easy_apply_index(labels)
        if index is not None:
            return toggles[index][0]

    # No toggle: only accept a control whose label names the filter, so a job's
    # bare "Easy Apply" apply button is never mistaken for it.
    labels = [label for _el, label in candidates]
    index = pick_easy_apply_filter_index(labels)
    if index is not None:
        return candidates[index][0]

    return None


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


async def _read_ai_candidates(page) -> list[dict]:
    payload = _loads(await _safe(page.evaluate(_AI_CANDIDATES_QUERY), ""))
    return list(payload.get("candidates") or [])


async def find_ai_job_search_button(page):
    """Return LinkedIn's "Try AI job search" control, or ``None`` when absent.

    Discovery is runtime and markup-agnostic: a JS scan collects visible
    interactive controls whose combined label mentions "search" or "AI", then the
    pure :func:`looks_like_ai_job_search` predicate picks the AI one.
    """
    candidates = await _read_ai_candidates(page)
    labels = [candidate.get("label", "") for candidate in candidates]
    index = pick_ai_job_search_index(labels)
    if index is None:
        return None
    marker = candidates[index].get("marker")
    return await _marker_element(page, "data-autojob-ai", marker) if marker else None


async def read_ai_job_search_candidates(page) -> list[str]:
    """Labels of the controls the AI scan saw, for diagnosing a miss."""
    return [candidate.get("label", "") for candidate in await _read_ai_candidates(page)]


async def wait_for_ai_job_search_button(page, settings: Settings):
    """Wait briefly for the optional AI job search control; return it or ``None``."""
    deadline = time.monotonic() + settings.session.ai_search_timeout_seconds
    button = await find_ai_job_search_button(page)
    while button is None and time.monotonic() < deadline:
        await asyncio.sleep(_APPLY_POLL_SECONDS)
        button = await find_ai_job_search_button(page)
    return button


async def click_ai_job_search(page, settings: Settings, button=None) -> bool:
    """Click LinkedIn's optional "Try AI job search" control when present.

    The control often navigates/reloads the page. A navigating click can make
    ``Element.click()`` raise *after* the navigation has already started (the CDP
    execution context is torn down), which is not a failed click. So a raised
    exception is discarded and success is judged from whether the URL changed,
    and the page load is awaited either way so the caller can repeat the search
    on the new page.
    """
    if button is None:
        button = await find_ai_job_search_button(page)
    if button is None:
        return False

    url_before = await _safe(page.get_url(), "") or ""
    await _safe(button.evaluate("() => this.scrollIntoView({block: 'center'})"))
    await _pace(settings)

    clicked = False
    try:
        await button.click()
        clicked = True
    except Exception:  # noqa: BLE001 - a navigating click may raise; judged below
        clicked = False
    if settings.session.post_click_wait_seconds:
        await asyncio.sleep(settings.session.post_click_wait_seconds)
    await _pace(settings)

    # The click may have triggered a navigation/reload; wait for it before the
    # caller repeats the search, and treat a changed URL as a successful click.
    await _wait_for_load(page, settings.session.navigation_timeout_ms / 1000)
    url_after = await _safe(page.get_url(), "") or ""
    if url_after and url_after != url_before:
        clicked = True
    return clicked


async def read_job_cards(page) -> list:
    """Return the job cards currently shown in the search results list."""
    # Ensure AI/semantic job cards are marked so [data-autojob-card] resolves them.
    await _mark_ai_job_cards(page)
    for selector in _JOB_CARD_SELECTORS:
        cards = await _query_elements(page, selector)
        if cards:
            return cards
    return []


async def _element_is_job_card(element) -> bool:
    """True when ``element`` is a job card, not the details pane's apply button.

    AI/semantic job cards are ``div[role="button"]`` marked with
    ``data-autojob-card`` (see :data:`_JOB_CARD_ATTR`). Their accessible text
    also carries "Easy Apply", so without this check the fallback scan would
    mistake the first card for the apply button and click it instead of the blue
    "Easy Apply" button (the Task 2 bug).

    A real apply button is a ``<button>`` and is never excluded by the label
    heuristic, so a job whose title/company contains a location word (e.g.
    "Remote") is still matched.
    """
    if await _safe(element.get_attribute(_JOB_CARD_ATTR), None) is not None:
        return True
    tag = await _safe(element.evaluate("() => this.tagName"), "") or ""
    if str(tag).upper() == "BUTTON":
        return False
    return looks_like_job_card_label(await _element_label(element))


async def find_job_apply_button(page) -> tuple:
    """Return ``(element, label)`` for the details pane's apply button, or ``(None, "")``."""
    # Ensure AI/semantic job cards are marked so the fallback scan below can
    # exclude them: a job card's "Easy Apply" badge is not the apply button.
    await _mark_ai_job_cards(page)
    button = await _first_element(page, _JOB_DETAILS_APPLY_SELECTORS)
    if button is not None:
        return button, await _element_label(button)

    # Fall back to scanning interactive controls for an Easy Apply *action*
    # (an Easy Apply label that is not the results filter). Job cards are
    # excluded — their text also contains "Easy Apply" but they are not the
    # blue apply button.
    controls = await _query_elements(page, "button, [role='button']")
    labels = [await _element_label(element) for element in controls]
    candidates = [
        (element, label)
        for element, label in zip(controls, labels)
        if looks_like_easy_apply_action(label) and not await _element_is_job_card(element)
    ]
    index = pick_easy_apply_action_index([label for _element, label in candidates])
    return (candidates[index][0], candidates[index][1]) if index is not None else (None, "")


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


async def read_form(page) -> tuple[bool, str, list[dict]]:
    """Return ``(form_open, step_title, fields)`` for the open form (Task 4)."""
    payload = _loads(await _safe(page.evaluate(_ENUMERATE_FORM_QUERY), ""))
    return (
        bool(payload.get("open")),
        str(payload.get("title") or ""),
        list(payload.get("fields") or []),
    )


async def enumerate_form_fields(page) -> tuple[bool, list[dict]]:
    """Return ``(form_open, fields)`` for the open Easy Apply form (Task 4)."""
    opened, _title, fields = await read_form(page)
    return opened, fields


async def read_resume_info(page) -> dict:
    """Return the resume controls: ``options``, ``fileInput``, ``select``, ``uploadButton``.

    The form is dynamic, so the resume control may be a radio list, a
    ``<select>``, a file input, or an upload button that reveals the file input.
    """
    payload = _loads(await _safe(page.evaluate(_RESUME_OPTIONS_QUERY), ""))
    return {
        "options": list(payload.get("options") or []),
        "fileInput": bool(payload.get("fileInput")),
        "select": payload.get("select") or None,
        "uploadButton": payload.get("uploadButton") or None,
    }


async def read_resume_options(page) -> tuple[list[dict], bool]:
    """Return ``(listed_resume_options, file_input_present)`` for the form (Task 4)."""
    info = await read_resume_info(page)
    return info["options"], info["fileInput"]


async def read_form_buttons(page) -> list[dict]:
    """Return the Easy Apply modal's buttons (Task 4)."""
    payload = _loads(await _safe(page.evaluate(_FORM_BUTTONS_QUERY), ""))
    return list(payload.get("buttons") or [])


async def _marker_element(page, attribute: str, marker: str):
    return await _first_element(page, [f'[{attribute}="{marker}"]'])


# Placeholder values a <select> may show before a real choice is made. A select
# holding one of these is still unanswered; anything else is treated as answered.
_SELECT_PLACEHOLDERS = {
    "",
    "select",
    "select...",
    "select an option",
    "select one",
    "select option",
    "choose",
    "choose an option",
    "choose one",
    "none",
}


def _control_already_answered(field: dict) -> bool:
    """True when a form control already holds a real (non-placeholder) value.

    LinkedIn pre-fills controls from the profile (e.g. the "Email address" and
    "Phone country code" ``<select>``s). Those are already answered, so the agent
    must not ask the human about them or overwrite them with a guess.
    """
    kind = field.get("kind")
    if kind in {"radio", "checkbox"}:
        return bool(field.get("checked"))
    value = str(field.get("value") or "").strip()
    if not value:
        return False
    if kind == "select":
        return value.lower() not in _SELECT_PLACEHOLDERS
    return True


def _choice_hint(field: dict) -> str:
    """Human-readable list of a control's allowed options, for the banner."""
    choices = field.get("options") or []
    labels: list[str] = []
    for choice in choices:
        if isinstance(choice, dict):
            label = str(choice.get("text") or choice.get("value") or "").strip()
        else:
            label = str(choice).strip()
        if label:
            labels.append(label)
    if not labels:
        return ""
    return "One of: " + ", ".join(labels)


def _select_value_for(answer: str, options: list[dict]) -> str | None:
    """Resolve an answer to a ``<select>`` option value (matching text or value)."""
    for option in options:
        text = str(option.get("text") or "")
        value = str(option.get("value") or "")
        if answers_match(text, answer) or answers_match(value, answer):
            return value or text
    return None


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
    page,
    fields: list[dict],
    answers: dict[str, str],
    settings: Settings,
    ask=None,
    human: Task5Outcome | None = None,
) -> tuple[int, int, list[str], list[FormField]]:
    """Fill the known fields of one form step; leave the rest unknown.

    ``ask`` is Task 5's optional async ``(question, field) -> answer | None``
    callable. When the store cannot answer a question (or a stored radio answer
    matches none of the step's options), it is used to ask the human; a returned
    answer is filled, remembered in the store, and reused for later occurrences.
    """
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

    async def _apply(record: FormField, field: dict, answer: str, source: str) -> None:
        nonlocal known, filled
        record.known = True
        record.value = answer
        record.answered_by = source
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
        checked = next((g for g in group if g.get("checked")), None)
        if checked is not None:
            # Already selected on the form (e.g. a pre-filled choice): leave it be.
            record.known = True
            record.filled = True
            record.value = checked.get("option", "")
            record.answered_by = "form"
            known += 1
            filled += 1
            records.append(record)
            continue
        found = lookup_answer(answers, [question, key])
        answer = found[1] if found else None
        source = "store" if found else "human"
        option = (
            next((g for g in group if answers_match(g.get("option", ""), answer)), None)
            if answer is not None
            else None
        )
        # Ask the human only when we have no usable answer: nothing stored, or a
        # stored answer that matches none of this step's options.
        if option is None and ask is not None:
            answered = await ask(question, {"type": "radio", "options": options})
            if answered is not None:
                _remember_answer(settings, answers, human, question, answered)
                answer, source = answered, "human"
                option = next(
                    (g for g in group if answers_match(g.get("option", ""), answered)), None
                )
        if option is not None:
            await _apply(record, option, answer, source)
            continue
        if answer is None:
            unknown.append(question)
            records.append(record)
            continue
        record.known = True
        record.value = answer
        record.answered_by = source
        record.error = "no option matched the answer"
        known += 1
        records.append(record)

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
        if _control_already_answered(field):
            # The form already holds a real value (e.g. a pre-filled select): keep it.
            record.known = True
            record.filled = True
            record.value = str(field.get("value") or "")
            record.answered_by = "form"
            known += 1
            filled += 1
            records.append(record)
            continue
        found = lookup_answer(answers, [question, field.get("name", "")])
        answer = found[1] if found else None
        source = "store" if found else "human"
        if answer is None and ask is not None:
            answered = await ask(question, field)
            if answered is not None:
                _remember_answer(settings, answers, human, question, answered)
                answer, source = answered, "human"
        if answer is None:
            unknown.append(question)
            records.append(record)
            continue
        if field.get("kind") == "select":
            # A <select> only accepts one of its option values, so map the answer
            # (which may be the visible option text) to the real value.
            resolved = _select_value_for(answer, field.get("options") or [])
            if resolved is None and field.get("options"):
                record.error = "the answer did not match any option"
                unknown.append(question)
                records.append(record)
                continue
            if resolved is not None:
                answer = resolved
        if field.get("kind") == "checkbox" and str(answer).strip().lower() in {
            "no",
            "false",
            "0",
            "off",
        }:
            record.known = True
            record.value = answer
            record.filled = True
            record.answered_by = source
            known += 1
            filled += 1
            records.append(record)
            continue
        await _apply(record, field, answer, source)

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


async def _resume_file_selector(page) -> str | None:
    """CSS selector for the form's file input, if one is present on this step."""
    if await _first_element(page, ['[data-autojob-file="1"]']) is not None:
        return '[data-autojob-file="1"]'
    if await _first_element(page, ['input[type="file"]']) is not None:
        return 'input[type="file"]'
    return None


def _resume_listed_names(info: dict) -> list[str]:
    """Every resume name the form already lists (radio options and select choices)."""
    names = [option.get("label", "") for option in info.get("options", [])]
    select = info.get("select")
    if select:
        names += [choice.get("text", "") for choice in select.get("options", [])]
    return names


async def _attach_resume(
    page,
    session,
    resume_path: str,
    settings: Settings,
    outcome: Task4Outcome,
    notify,
) -> None:
    """Attach the Task 3 resume wherever it is on the dynamic form (Task 4).

    Prefers a resume already listed on the current step (a radio option or a
    ``<select>`` choice); otherwise uploads the file, clicking an "Upload
    resume" button first when that is what reveals the file input.
    """
    info = await read_resume_info(page)
    matched = pick_listed_resume(resume_path, _resume_listed_names(info))

    if matched:
        option = next((o for o in info.get("options", []) if o.get("label") == matched), None)
        if option is not None:
            element = await _marker_element(page, "data-autojob-resume", option["marker"])
            if element is not None:
                await _safe(element.click())
                if settings.session.post_click_wait_seconds:
                    await asyncio.sleep(settings.session.post_click_wait_seconds)
                outcome.resume_attached = True
                outcome.resume_selection = "listed"
                outcome.resume_listed_name = matched
                notify(f"Task 4: selected the listed resume {matched!r}.")
                return

        select = info.get("select")
        choice = (
            next((c for c in select["options"] if c.get("text") == matched), None)
            if select
            else None
        )
        if select is not None and choice is not None:
            element = await _marker_element(page, "data-autojob-resume-select", select["marker"])
            if element is not None:
                await element.evaluate(_FILL_SELECT_JS, str(choice["value"]))
                if settings.session.post_click_wait_seconds:
                    await asyncio.sleep(settings.session.post_click_wait_seconds)
                outcome.resume_attached = True
                outcome.resume_selection = "listed"
                outcome.resume_listed_name = matched
                notify(f"Task 4: selected the listed resume {matched!r}.")
                return

    selector = await _resume_file_selector(page)
    if selector is None and info.get("uploadButton"):
        upload = info["uploadButton"]
        element = await _marker_element(page, "data-autojob-resume-upload", upload["marker"])
        if element is not None:
            await _safe(element.click())
            if settings.session.post_click_wait_seconds:
                await asyncio.sleep(settings.session.post_click_wait_seconds)
            selector = await _resume_file_selector(page)

    if selector is None:
        # The form is dynamic, so the resume control may appear on a later step;
        # record it once (not on every step) but keep looking on subsequent steps.
        note = "no resume control found on this form step"
        if note not in outcome.notes:
            outcome.notes = _append_note(outcome.notes, note)
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


async def run_ai_job_search_detour(
    page,
    search_query: str,
    settings: Settings,
    notify,
    outcome: Task1Outcome,
) -> None:
    """Click the optional "Try AI job search" control and repeat the search.

    The control is optional: when it is absent the search is performed only once
    and this returns without changing the outcome. When it is present, each click
    is followed by a repeat "software engineer" search, and the click/repeat pair
    is retried while the control reappears — up to ``_MAX_AI_JOB_SEARCH_CLICKS`` so
    a persistent control can never loop forever. Searching follows LinkedIn's
    normal behaviour and may reload or navigate the page.

    Once the control is clicked the run stays in LinkedIn's AI (semantic) search
    mode: it never navigates back to the classic jobs search. A repeat search that
    returns no results simply ends the re-click loop and the outcome reflects the
    AI search.
    """
    for _ in range(_MAX_AI_JOB_SEARCH_CLICKS):
        ai_button = await wait_for_ai_job_search_button(page, settings)
        if ai_button is None:
            break

        outcome.ai_job_search_present = True
        notify("Task 1: 'Try AI job search' button found; clicking it.")
        if not await click_ai_job_search(page, settings, ai_button):
            outcome.notes = _append_note(
                outcome.notes,
                "Try AI job search button was present but could not be clicked",
            )
            return

        outcome.ai_job_search_clicked = True
        outcome.ai_job_search_clicks += 1
        notify("Task 1: repeating the job search after AI job search.")
        found, count, url = await open_jobs_search(page, search_query, settings)
        outcome.results_found = found
        outcome.results_count = count
        outcome.search_url = url
        if not found:
            # Stay in the AI mode: a repeat that returns nothing just ends the
            # re-click loop. Never fall back to the classic search.
            break

    if not outcome.ai_job_search_present:
        # Nothing matched. Record the labels the scan actually saw so a real-run
        # miss (different wording/markup) is diagnosable.
        outcome.ai_job_search_candidates = await read_ai_job_search_candidates(page)
        if outcome.ai_job_search_candidates:
            outcome.notes = _append_note(
                outcome.notes,
                "AI job search not matched; controls seen: "
                + "; ".join(outcome.ai_job_search_candidates[:10]),
            )


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
            await run_ai_job_search_detour(page, search_query, settings, notify, outcome)
            selected, note = await select_easy_apply_filter(page, settings)
            outcome.easy_apply_filter_selected = selected
            outcome.notes = _append_note(outcome.notes, note)

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
        label = await _element_label(card)
        title = _first_line(label)
        # Task 6: skip cards already marked "Applied" (never click them). The
        # status text is read from the card itself; a card with no readable
        # status is treated as unapplied and left to the Easy Apply check.
        if settings.session.skip_applied and card_is_applied(label):
            outcome.applied_jobs_skipped += 1
            outcome.applied_skipped_cards.append({"index": index, "title": title})
            notify(f"Task 2: job {index + 1} is already applied; skipping.")
            continue
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

    if not outcome.easy_apply_clicked:
        # Task 6: when every card on this page was skipped as Applied, stop
        # gracefully with a clear note instead of opening (and applying to) one.
        if outcome.jobs_seen and outcome.applied_jobs_skipped >= outcome.jobs_seen:
            outcome.notes = _append_note(
                outcome.notes,
                "no unapplied job found on this page; every job card is already Applied",
            )
        elif outcome.applied_jobs_skipped:
            outcome.notes = _append_note(
                outcome.notes,
                f"skipped {outcome.applied_jobs_skipped} applied job(s); "
                "no unapplied Easy Apply job was opened",
            )
    return outcome


def _form_signature(title: str, fields: list[dict]) -> str:
    """A stable fingerprint of a form step, to detect that Next did not advance."""
    parts = [title or ""]
    for field in fields:
        parts.append(
            "|".join(str(field.get(key, "")) for key in ("kind", "question", "name", "option"))
        )
    return "\n".join(parts)


def _blocking_questions(records: list[FormField]) -> list[str]:
    """Required questions on a step that are still unanswered (they block Next)."""
    blocking: list[str] = []
    for record in records:
        if record.required and not record.known and record.question not in blocking:
            blocking.append(record.question)
    return blocking


def _blocked_note(prefix: str, blocking: list[str]) -> str:
    """A clear "why the form stopped" note, naming the required unknown answers."""
    if blocking:
        return (
            f"{prefix}; required questions are unanswered: "
            + ", ".join(blocking)
            + " - stopping before Submit"
        )
    return f"{prefix}; stopping before Submit"


async def _task4_on_page(
    page,
    session,
    resume_path: str | None,
    answers: dict[str, str],
    settings: Settings,
    notify,
    human: Task5Outcome | None = None,
) -> Task4Outcome:
    """Fill the open Easy Apply form and attach the resume, without submitting.

    The form is dynamic: its steps, fields, and resume control (radio list,
    ``<select>``, file input, or an upload button that reveals one) are
    discovered at runtime rather than assumed. The walk stops at the terminal
    step (only Submit is left), or as soon as a step fails to advance.

    Task 5 rides along: when a question is unknown and ``ask_human`` is on, the
    run pauses on a browser banner and reads the answer the human types into the
    form field. Answers are remembered so the same question is filled
    automatically next time. The optional ``human`` tracker records the questions
    asked, answered, skipped, and timed out.
    """
    outcome = Task4Outcome(resume_path=resume_path or "")
    human = human if human is not None else Task5Outcome()
    human.enabled = bool(settings.session.ask_human)

    asker = None
    if human.enabled:

        async def _ask_question(question: str, field: dict) -> str | None:
            return await ask_human_for_answer(
                page,
                question,
                field.get("type", ""),
                _choice_hint(field),
                settings,
                notify,
                human,
            )

        asker = _ask_question

    previous: str | None = None
    pending_advance = False
    blocking: list[str] = []

    for step in range(_MAX_FORM_STEPS):
        opened, title, fields = await read_form(page)
        if not opened:
            if step == 0:
                outcome.notes = _append_note(outcome.notes, "Easy Apply form was not found")
            break

        signature = _form_signature(title, fields)
        if pending_advance:
            if signature == previous:
                # The click did not move to a new step: stop instead of retrying
                # blindly, naming the required answers that are still unknown.
                outcome.notes = _append_note(
                    outcome.notes, _blocked_note("form did not advance to a new step", blocking)
                )
                break
            outcome.steps_advanced += 1
            pending_advance = False
        previous = signature

        outcome.form_open = True
        outcome.fields_enumerated += len(fields)
        known, filled, unknown, records = await _fill_step(
            page, fields, answers, settings, ask=asker, human=human
        )
        outcome.known_fields += known
        outcome.filled_fields += filled
        outcome.unknown_fields.extend(unknown)
        outcome.fields.extend(records)

        if resume_path and not outcome.resume_attached:
            await _attach_resume(page, session, resume_path, settings, outcome, notify)

        buttons = await read_form_buttons(page)
        button = pick_next_button(buttons)
        if button is None:
            # No enabled Next/Continue on this step. Say *why* we stopped: a
            # disabled navigation button usually means a required answer is
            # missing, otherwise this is the terminal step (only Submit remains).
            blocking = _blocking_questions(records)
            if any(looks_like_next(b.get("text", "")) for b in buttons):
                outcome.notes = _append_note(
                    outcome.notes, _blocked_note("the only navigation button is disabled", blocking)
                )
            else:
                outcome.notes = _append_note(
                    outcome.notes, "reached the last step (only Submit remains)"
                )
            break

        element = await _marker_element(page, "data-autojob-btn", button["marker"])
        if element is None:
            outcome.notes = _append_note(
                outcome.notes, "navigation button disappeared before it could be clicked"
            )
            break

        blocking = _blocking_questions(records)
        notify(f"Task 4: advancing form step via {button.get('text')!r}.")
        await _safe(element.click())
        pending_advance = True
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
) -> tuple[Task4Outcome, Task5Outcome]:
    """Fill the open Easy Apply form in the session registered under ``run_id``.

    Returns ``(task4, task5)``. The session is left open; the caller closes it (the
    graph's ``cleanup`` node or :func:`run_full_agent`), so an in-flight session
    can still be screenshotted on failure.
    """
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
    from src.tools.resumes import select_best_resume  # local import keeps this light

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
