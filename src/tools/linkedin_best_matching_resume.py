"""Task 3: read the open job's description and pick the best-matching resume.

This module owns Task 3 in full, gathered from the two places its code used to
live (the description reader in :mod:`src.tools.browser`, the resume selection in
``src.tools.resumes``):

1. Read the description of the job that is open in the details pane: title,
   company, location, and the full description body.
2. Read every resume in the configured folder, extract its readable text
   (``.pdf``, ``.docx``, ``.txt``, ``.md``), score each one against the job
   description with :mod:`src.tools.matching`, and select the highest scorer.

Ties are broken by the most recently modified file. Resume files are never
modified. Reading the description is a deterministic CDP ``page.evaluate`` (no
LLM), and the scoring is deterministic keyword/weight matching.

**Subtask 3.1** extends the selection: when nothing in the folder matches the job
at all, the agent first reuses a resume it already remembered for a similar job
(:mod:`src.tools.resume_library`); otherwise it asks the human to upload one in
the browser, stores that file in the pool, and remembers it for similar jobs.
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
from src.tools.matching import score_resume
from src.tools.resume_library import (
    RESUME_SUFFIXES,
    find_reusable_resume,
    load_library,
    remember_resume,
    store_uploaded_resume,
)

_DOCX_TEXT_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"

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


def select_best_resume(
    job_description: JobDescription,
    resumes_dir: str | Path,
) -> Task3Outcome:
    """Score every resume in ``resumes_dir`` and select the best match."""
    files = list_resume_files(resumes_dir)
    outcome = Task3Outcome(
        job_description=job_description,
        resumes_dir=str(resumes_dir),
        resumes_found=len(files),
    )

    if not files:
        outcome.notes = "no resumes available in the folder"
        return outcome

    for path in files:
        error = ""
        try:
            text = extract_resume_text(path)
        except Exception as exc:  # noqa: BLE001 - a bad file must not stop the run
            text = ""
            error = f"{type(exc).__name__}: {exc}"

        result = score_resume(job_description.title, job_description.full_text, text)
        outcome.candidates.append(
            ResumeCandidate(
                path=str(path),
                score=result.score,
                matched_keywords=list(result.matched_skills),
                rationale=result.rationale,
                extracted=bool(text.strip()) and not error,
                error=error,
            )
        )

    # Prefer resumes whose text was read; only fall back to unreadable files when
    # nothing could be extracted at all.
    pool = [candidate for candidate in outcome.candidates if candidate.extracted] or list(
        outcome.candidates
    )
    best_score = max(candidate.score for candidate in pool)
    top = [candidate for candidate in pool if candidate.score == best_score]
    if len(top) > 1:
        # Tie-break: prefer the most recently modified file and record the tie.
        top.sort(key=lambda candidate: _safe_mtime(candidate.path), reverse=True)
        outcome.tie_break = (
            f"tie at score {best_score} across {len(top)} resumes; "
            "chose the most recently modified file"
        )

    best = top[0]
    outcome.selected_path = best.path
    outcome.selected_score = best.score
    outcome.rationale = best.rationale

    unreadable = [candidate.path for candidate in outcome.candidates if candidate.error]
    notes = [outcome.tie_break] if outcome.tie_break else []
    if unreadable:
        notes.append(f"could not read {len(unreadable)} resume(s): {', '.join(unreadable)}")
    outcome.notes = "; ".join(part for part in notes if part)
    return outcome


def _safe_mtime(path: str) -> float:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


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


def no_match(outcome: Task3Outcome, min_score: float = 0.0) -> bool:
    """True when nothing in the pool matched the job (Task 3.1's trigger)."""
    if outcome.selected_path is None:
        return True
    return (outcome.selected_score or 0.0) <= min_score


def _score_path(description: JobDescription, path: str) -> float:
    """Score one resume file against the job (0.0 when it cannot be read)."""
    try:
        text = extract_resume_text(path)
    except Exception:  # noqa: BLE001 - an unreadable resume must not stop the run
        return 0.0
    return score_resume(description.title, description.full_text, text).score


async def ensure_resume(
    description: JobDescription,
    resumes_dir: str | Path,
    settings: Settings,
    page=None,
    notify=None,
    asker=None,
) -> Task3Outcome:
    """Select the best resume, falling back to the human when nothing matches.

    Task 3.1: when no resume matches the job, reuse one already remembered for a
    similar job; otherwise ask the human for a resume in the browser, store it in
    the pool, remember its job profile, and use it. ``asker`` is injectable for
    tests (it defaults to :func:`ask_human_for_resume`).
    """
    notify = notify or (lambda _message: None)
    outcome = select_best_resume(description, resumes_dir)
    if not no_match(outcome, settings.resume_min_score):
        return outcome

    outcome.no_match = True
    # Nothing really matches, so do not apply with the (score-0) best candidate:
    # only a remembered or human-provided resume is used from here on.
    outcome.selected_path = None
    outcome.selected_score = None
    reusable = find_reusable_resume(
        load_library(settings.resume_library_file), description, resumes_dir
    )
    if reusable:
        outcome.selected_path = reusable
        outcome.reused_from_library = reusable
        outcome.selected_score = _score_path(description, reusable)
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

    remember_resume(settings.resume_library_file, description, str(stored))
    outcome.human_resume_path = str(stored)
    outcome.selected_path = str(stored)
    outcome.selected_score = _score_path(description, str(stored))
    outcome.rationale = f"human-provided resume {stored.name!r} for a job nothing matched"
    outcome.resumes_found = len(list_resume_files(resumes_dir))
    outcome.candidates.append(
        ResumeCandidate(
            path=str(stored),
            score=outcome.selected_score or 0.0,
            rationale=outcome.rationale,
            extracted=bool(extract_resume_text(stored).strip()),
        )
    )
    outcome.notes = _append_note(
        outcome.notes, f"stored and remembered the uploaded resume {stored!r}"
    )
    notify(f"Task 3.1: stored {stored.name!r} and remembered it for similar jobs.")
    return outcome
