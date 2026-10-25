"""Task 3.1: ask the human for a resume in a browser banner.

When no resume in the pool matches a job, the run pauses instead of guessing:
the banner carries its own file picker, and it also picks up a file dropped into
the form's own resume control. The file is read as a data URL and handed back to
the caller, which stores and describes it.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import time

from src.configuration import Settings
from src.tools.browser import _loads, _safe
from src.tools.linkedin_status_overlay import emit_step

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


__all__ = [
    "DEFAULT_RESUME_PROMPT",
    "ask_human_for_resume",
]
