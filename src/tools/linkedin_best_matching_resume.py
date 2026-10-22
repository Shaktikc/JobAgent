"""Task 3: read the open job's description and pick the best-matching resume.

This module owns Task 3 in full:

1. Read the description of the job that is open in the details pane: title,
   company, location, and the full description body.
2. Ask the **LLM** (Task 3.2) to choose the resume from the pool that best fits
   that description, using a short LLM-written profile of each resume
   (:mod:`src.tools.resume_descriptions`). The LLM is the **only** matching path —
   there is no deterministic scoring fallback.

Reading the description is a deterministic CDP ``page.evaluate`` (no LLM).

**Subtask 3.1** handles the "no match" case: when the LLM answers **none**, the
agent first reuses a resume it already remembered for a similar job
(:mod:`src.tools.resume_library`); otherwise it asks the human to upload one in
the browser, stores that file in the pool, has the **LLM** describe it, and
remembers it for similar jobs. Resume files are never modified.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from src.configuration import Settings
from src.state import JobDescription, ResumeCandidate, Task3Outcome
from src.tools.browser import _append_note, _loads, _safe
from src.tools.linkedin_status_overlay import emit_llm, emit_step
from src.tools.resume_descriptions import (
    ResumeDescriptionError,
    describe_resume,
    described_candidates,
    ensure_descriptions,
    load_descriptions,
    pick_best_resume,
    store_description,
)
from src.tools.resume_library import (
    RESUME_SUFFIXES,
    find_reusable_resume,
    load_library,
    remember_resume,
    store_uploaded_resume,
)

_DOCX_TEXT_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"

# The open job's details (Task 3): title, company, location, and description body.
#
# LinkedIn serves several layouts for the same job. Besides the classic two-pane
# results page, a job can be a newer full-page view whose description sits in
# ``.description__text`` / ``.show-more-less-html__markup`` or, on the AI/semantic
# job view, behind *hashed* CSS-in-JS class names with no stable selector at all.
# The classic selectors are tried first; then the newer BEM containers; then a
# class-agnostic fallback that reads the paragraph/list text of the details pane.
# The title also falls back to the document title so the match still has *some*
# signal when the view is hashed.
_JOB_DESCRIPTION_QUERY = r"""
() => {
  const clean = (text) => (text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
  const first = (selectors, minimum) => {
    for (const selector of selectors) {
      let el = null;
      try { el = document.querySelector(selector); } catch (err) { continue; }
      const text = el ? clean(el.innerText) : '';
      if (text.length >= (minimum || 1)) return text;
    }
    return '';
  };
  const detailsRoot = () => {
    const roots = [
      'div.jobs-search__job-details--container',
      'div.scaffold-layout__detail',
      'div.job-view-layout',
      'section.jobs-details',
      'div.jobs-details',
      'main',
      '[role="main"]'
    ];
    for (const selector of roots) {
      let el = null;
      try { el = document.querySelector(selector); } catch (err) { continue; }
      if (el && clean(el.innerText)) return el;
    }
    return document.body;
  };
  // Class-agnostic fallback: job descriptions are paragraph/list based, so read
  // every paragraph/li under the details pane. This survives LinkedIn's hashed
  // CSS-in-JS class names (the AI/semantic job view) where no stable selector
  // matches the description container.
  const paragraphText = () => {
    const root = detailsRoot();
    if (!root) return '';
    const parts = [];
    const seen = new Set();
    for (const el of root.querySelectorAll('p, li')) {
      const text = clean(el.innerText);
      if (text.length < 20 || text.length > 4000 || seen.has(text)) continue;
      seen.add(text);
      parts.push(text);
    }
    return parts.join('\n');
  };
  const title = first([
    '.job-details-jobs-unified-top-card__job-title',
    '.jobs-unified-top-card__job-title',
    '.top-card-layout__title',
    '.topcard__title',
    'h1.t-24', 'h1', 'h2',
    '[class*="job-title"]'
  ]) || clean(document.title).replace(/\s*\|\s*LinkedIn\s*$/i, '');
  const company = first([
    '.job-details-jobs-unified-top-card__company-name',
    '.jobs-unified-top-card__company-name',
    '.topcard__org-name-link',
    'a.topcard__org-name-link',
    '[class*="company-name"]'
  ]);
  const locationText = first([
    '.job-details-jobs-unified-top-card__bullet',
    '.jobs-unified-top-card__bullet',
    '.topcard__flavor--bullet'
  ]);
  const body =
    first([
      '.jobs-description__content',
      '.jobs-box__html-content',
      '#job-details',
      '.jobs-description'
    ]) ||
    first(['.description__text', '.show-more-less-html__markup']) ||
    first(['[class*="description"]'], 200) ||
    paragraphText();
  return JSON.stringify({
    title: title,
    company: company,
    location: locationText,
    body: body,
    url: location.href
  });
}
"""


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


def list_resume_files(resumes_dir: str | Path) -> list[Path]:
    """Return the readable resume files in ``resumes_dir`` (sorted by name)."""
    directory = Path(resumes_dir)
    if not directory.is_dir():
        return []
    files = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in RESUME_SUFFIXES
    ]
    return sorted(files, key=lambda path: path.name.lower())


def extract_resume_text(path: str | Path) -> str:
    """Return the readable text of a resume file, or ``""`` for unknown formats."""
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return file_path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        return _extract_pdf(file_path)
    if suffix == ".docx":
        return _extract_docx(file_path)
    return ""


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader  # lazy: only needed for PDF resumes

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_docx(path: Path) -> str:
    """Extract text from a ``.docx`` using only the standard library."""
    try:
        with zipfile.ZipFile(path) as archive:
            document_xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile, OSError):
        return ""
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError:
        return ""
    return " ".join(node.text or "" for node in root.iter(_DOCX_TEXT_TAG))


# --- Task 3.1: ask the human for a resume when nothing matched -------------

# Task 3.1's banner carries its own file picker, so the human can upload a resume
# without depending on which step the Easy Apply form is on. It also picks up a
# file dropped into the form's own resume control, so the human may upload there
# instead. The file is read as a data URL and handed back to the agent, which
# stores it in the pool. Message text is set via ``textContent`` (never markup).
_SHOW_RESUME_JS = r"""
(message) => {
  let box = document.getElementById('autojob-resume');
  if (!box) {
    box = document.createElement('div');
    box.id = 'autojob-resume';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', 'AutoJobApply needs a resume');
    box.style.cssText = [
      'position:fixed', 'right:24px', 'bottom:24px', 'z-index:2147483647',
      'max-width:420px', 'background:#ffffff', 'color:#1a1a1a',
      'border:2px solid #b24020', 'border-radius:8px',
      'box-shadow:0 8px 24px rgba(0,0,0,.35)', 'padding:16px',
      "font:14px/1.4 -apple-system,'Segoe UI',Roboto,Arial,sans-serif"
    ].join(';');
    const heading = document.createElement('div');
    heading.textContent = 'AutoJobApply needs a resume';
    heading.style.cssText = 'font-weight:600;color:#b24020;margin-bottom:8px';
    const msg = document.createElement('div');
    msg.id = 'autojob-resume-message';
    msg.style.cssText = 'margin-bottom:8px;color:#555;font-size:13px';
    const input = document.createElement('input');
    input.type = 'file';
    input.id = 'autojob-resume-input';
    input.accept = '.pdf,.docx,.txt,.md';
    input.style.cssText = 'display:block;margin-bottom:8px';
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:8px;justify-content:flex-end';
    const skip = document.createElement('button');
    skip.id = 'autojob-resume-skip';
    skip.type = 'button';
    skip.textContent = 'Skip';
    skip.style.cssText = 'padding:6px 12px;border:1px solid #666;border-radius:4px;cursor:pointer';
    skip.addEventListener('click', () => box.setAttribute('data-autojob-state', 'skipped'));
    row.appendChild(skip);
    box.appendChild(heading);
    box.appendChild(msg);
    box.appendChild(input);
    box.appendChild(row);
    document.body.appendChild(box);
  }
  box.setAttribute('data-autojob-state', 'pending');
  const msg = document.getElementById('autojob-resume-message');
  if (msg) msg.textContent = message || 'Upload a resume to continue.';
  return true;
}
"""

# Task 3.1: read the chosen file as a data URL. A single document-level listener
# is installed once and reset for each question, so the agent can poll without
# blocking. It watches the banner's picker and the form's own file input.
_WATCH_RESUME_FILE_JS = r"""
() => {
  const KEY = '__autojobResumeFile';
  const previous = window[KEY];
  if (previous && previous.installed) {
    previous.done = false;
    previous.name = '';
    previous.data = '';
    previous.error = '';
    return true;
  }
  const state = { installed: true, done: false, name: '', data: '', error: '' };
  window[KEY] = state;
  const read = (file) => {
    if (!file) return;
    try {
      const reader = new FileReader();
      reader.onload = () => {
        state.name = file.name || '';
        state.data = reader.result || '';
        state.done = true;
      };
      reader.onerror = () => { state.error = 'could not read the file'; state.done = true; };
      reader.readAsDataURL(file);
    } catch (err) {
      state.error = String(err);
      state.done = true;
    }
  };
  const fromInput = (el) => {
    if (el && el.tagName === 'INPUT' && el.type === 'file' && el.files && el.files.length) {
      read(el.files[0]);
    }
  };
  document.addEventListener('change', (e) => fromInput(e.target), true);
  const bannerInput = document.getElementById('autojob-resume-input');
  fromInput(bannerInput);
  const formInput = document.querySelector('input[type="file"]');
  if (formInput && formInput !== bannerInput) fromInput(formInput);
  return true;
}
"""

# Task 3.1: read the banner state and the uploaded file (name + data URL).
_READ_RESUME_FILE_JS = r"""
() => {
  const box = document.getElementById('autojob-resume');
  const state = box ? (box.getAttribute('data-autojob-state') || 'pending') : '';
  const file = window.__autojobResumeFile;
  if (!file) return JSON.stringify({ present: !!box, state: state, done: false });
  return JSON.stringify({
    present: !!box,
    state: state,
    done: !!file.done,
    name: file.name || '',
    data: file.data || '',
    error: file.error || ''
  });
}
"""

# Task 3.1: remove the banner and reset the watcher once the question is resolved.
_HIDE_RESUME_JS = r"""
() => {
  const box = document.getElementById('autojob-resume');
  if (box) box.remove();
  const file = window.__autojobResumeFile;
  if (file) {
    file.done = false;
    file.name = '';
    file.data = '';
    file.error = '';
  }
  return true;
}
"""

DEFAULT_RESUME_PROMPT = (
    "No resume matched this job. Upload a resume (PDF, DOCX, TXT, or MD) and the "
    "agent will save it and reuse it for similar jobs."
)


def _decode_data_url(data_url: str) -> bytes:
    """Decode a ``data:<mime>;base64,<payload>`` string to bytes (empty on error)."""
    if "," not in (data_url or ""):
        return b""
    try:
        return base64.b64decode(data_url.split(",", 1)[1])
    except (binascii.Error, ValueError):
        return b""


async def ask_human_for_resume(
    page,
    settings: Settings,
    notify,
    message: str = "",
) -> tuple[str, bytes] | None:
    """Task 3.1: ask the human to upload a resume in the browser banner.

    Returns ``(filename, content)`` for the uploaded file, or ``None`` when the
    human skipped or the wait timed out. The run pauses here (polling the page)
    instead of guessing, exactly like Task 5's answer banner.
    """
    await _safe(page.evaluate(_WATCH_RESUME_FILE_JS))
    shown = await _safe(page.evaluate(_SHOW_RESUME_JS, message or DEFAULT_RESUME_PROMPT))
    if not shown:
        notify("Task 3.1: could not show the resume banner.")
        return None

    notify(
        "Task 3.1: no resume matched this job; upload a resume in the banner in "
        "the browser window."
    )
    emit_step(notify, "Waiting for you - upload a resume in the banner to continue.")
    deadline = time.monotonic() + settings.session.ask_timeout_seconds
    while time.monotonic() < deadline:
        payload = _loads(await _safe(page.evaluate(_READ_RESUME_FILE_JS), ""))
        if str(payload.get("state") or "") == "skipped":
            await _safe(page.evaluate(_HIDE_RESUME_JS))
            notify("Task 3.1: you skipped providing a resume.")
            return None
        if payload.get("done"):
            await _safe(page.evaluate(_HIDE_RESUME_JS))
            if payload.get("error"):
                notify(f"Task 3.1: could not read the uploaded resume ({payload['error']}).")
                return None
            content = _decode_data_url(str(payload.get("data") or ""))
            if not content:
                notify("Task 3.1: the uploaded resume was empty.")
                return None
            notify(f"Task 3.1: received the resume {payload.get('name')!r} from the browser.")
            return str(payload.get("name") or "resume"), content
        await asyncio.sleep(settings.session.ask_poll_seconds)

    await _safe(page.evaluate(_HIDE_RESUME_JS))
    notify("Task 3.1: timed out waiting for a resume.")
    return None


# --- Task 3 main flow: describe the pool, let the LLM pick, else fall back --


async def ensure_resume(
    description: JobDescription,
    resumes_dir: str | Path,
    settings: Settings,
    page=None,
    notify=None,
    asker=None,
    describer=None,
    matcher=None,
) -> Task3Outcome:
    """Select the best resume, falling back to the human when nothing matches.

    Task 3.2: every resume in the pool is described by the **LLM**, then the LLM
    chooses the single best match (or **none**). Task 3.1: when the LLM answers
    **none**, reuse a resume already remembered for a similar job; otherwise ask
    the human for one in the browser, store it in the pool, have the **LLM**
    describe it, and use it directly. ``asker``/``describer``/``matcher`` are
    injectable for tests.
    """
    notify = notify or (lambda _message: None)
    files = list_resume_files(resumes_dir)
    outcome = Task3Outcome(
        job_description=description,
        resumes_dir=str(resumes_dir),
        resumes_found=len(files),
    )
    store_path = settings.resume_descriptions_file
    job_label = description.title.strip() or "this job"
    emit_step(
        notify,
        f"Please wait - choosing the best resume for {job_label!r} "
        f"from {len(files)} resume(s)...",
    )
    described_count = {"n": 0}

    async def _describe_with_status(path):
        described_count["n"] += 1
        emit_llm(
            notify,
            f"summarizing resume {Path(path).name!r} "
            f"({described_count['n']} of {len(files)})...",
        )
        description = await describe_resume(path, settings)
        emit_llm(
            notify,
            f"described resume {Path(path).name!r}",
            description.summary or "(no summary)",
        )
        return description

    describe = describer or _describe_with_status
    pick = matcher or (lambda job, candidates: pick_best_resume(job, candidates, settings))

    # Task 3.2: describe every resume, then let the LLM choose (no fallback).
    try:
        await ensure_descriptions(
            resumes_dir, store_path, settings, files=files, describe=describe
        )
        candidates = described_candidates(files, load_descriptions(store_path))
    except ResumeDescriptionError as exc:
        outcome.error = f"match: {exc}"
        outcome.notes = _append_note(outcome.notes, "could not describe the resume pool")
        notify(f"Task 3.2: {exc}")
        return outcome

    for path, candidate in candidates:
        outcome.candidates.append(
            ResumeCandidate(path=path, summary=candidate.summary, described=True)
        )

    emit_llm(
        notify,
        f"choosing the best-matching resume for {job_label!r} "
        f"from {len(candidates)} resume(s)...",
    )
    try:
        result = await pick(description, candidates)
    except ResumeDescriptionError as exc:
        outcome.error = f"match: {exc}"
        outcome.notes = _append_note(outcome.notes, "the LLM could not choose a resume")
        notify(f"Task 3.2: {exc}")
        emit_llm(notify, f"could not choose a resume for {job_label!r}", str(exc))
        return outcome

    if result.selected_path:
        outcome.selected_path = result.selected_path
        outcome.rationale = result.rationale or "the LLM chose the best-matching resume"
        outcome.notes = _append_note(outcome.notes, "the LLM chose the best-matching resume")
        emit_llm(
            notify,
            f"chose resume {Path(result.selected_path).name!r} for {job_label!r}",
            result.rationale,
        )
        return outcome

    # No resume matched the job: hand off to Task 3.1.
    outcome.no_match = True
    outcome.rationale = result.rationale or "the LLM found no matching resume"
    emit_llm(notify, f"no resume matched {job_label!r}", result.rationale)
    reusable = find_reusable_resume(
        load_library(settings.resume_library_file), description, resumes_dir
    )
    if reusable:
        outcome.selected_path = reusable
        outcome.reused_from_library = reusable
        outcome.rationale = (
            f"no resume matched, but {Path(reusable).name!r} was remembered for a similar job"
        )
        outcome.notes = _append_note(outcome.notes, f"reused the remembered resume {reusable!r}")
        notify(f"Task 3.1: reusing {Path(reusable).name!r} from a similar job.")
        return outcome

    if page is None or not settings.session.ask_human:
        outcome.notes = _append_note(
            outcome.notes, "no resume matched and asking the human is unavailable"
        )
        return outcome

    outcome.asked_human = True
    provided = await (asker or ask_human_for_resume)(page, settings, notify)
    if provided is None:
        outcome.notes = _append_note(outcome.notes, "the human did not provide a resume")
        return outcome

    filename, content = provided
    try:
        stored = store_uploaded_resume(resumes_dir, filename, content)
    except ValueError as exc:
        outcome.notes = _append_note(outcome.notes, f"could not store the uploaded resume: {exc}")
        return outcome

    # Task 3.2: describe the uploaded resume before it is used (no fallback).
    try:
        uploaded = await describe(stored)
    except ResumeDescriptionError as exc:
        outcome.error = f"match: {exc}"
        outcome.notes = _append_note(outcome.notes, "the uploaded resume could not be described")
        notify(f"Task 3.2: {exc}")
        return outcome

    store_description(store_path, stored, uploaded)
    remember_resume(settings.resume_library_file, description, str(stored))
    outcome.human_resume_path = str(stored)
    outcome.selected_path = str(stored)
    outcome.rationale = f"human-provided resume {stored.name!r} for a job nothing matched"
    outcome.resumes_found = len(list_resume_files(resumes_dir))
    outcome.candidates.append(
        ResumeCandidate(path=str(stored), summary=uploaded.summary, described=True)
    )
    outcome.notes = _append_note(
        outcome.notes, f"stored, described and remembered the uploaded resume {stored!r}"
    )
    notify(f"Task 3.1: stored {stored.name!r}, described it, and remembered it for similar jobs.")
    return outcome


__all__ = [
    "DEFAULT_RESUME_PROMPT",
    "ask_human_for_resume",
    "ensure_resume",
    "extract_resume_text",
    "list_resume_files",
    "read_job_description",
]
