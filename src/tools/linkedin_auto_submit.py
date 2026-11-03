"""Task 22: submit a validated Easy Apply form once, then confirm the result."""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.configuration import Settings
from src.state import Task4Outcome
from src.tools.browser import FIND_APPLY_ROOT_JS, _loads, _marker_element, get_run
from src.tools.forms import looks_like_next
from src.tools.linkedin_apply_loop import _dismiss_confirmation, _read_state
from src.tools.linkedin_easy_apply_fill.checkbox_groups import group_counts, group_key
from src.tools.linkedin_easy_apply_fill.field_filling import _control_already_answered
from src.tools.linkedin_easy_apply_fill.form_queries import read_form, read_form_buttons
from src.tools.linkedin_status_overlay import emit_step
from src.tools.linkedin_submission import submission_detected
from src.tools.linkedin_submission_evidence import capture_submission_failure
from src.tools.linkedin_validation.detection import read_rejections
from src.tools.self_healing.fingerprint import fill_failure_reason

_SUBMIT_LABELS = {"submit", "submit application", "submit your application"}
_READ_TIMEOUT = 15.0


@dataclass(frozen=True)
class AutoSubmitResult:
    status: str
    reason: str = ""
    evidence_path: str = ""


def _is_linkedin_jobs_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    return (parsed.scheme == "https" and (host == "linkedin.com" or host.endswith(".linkedin.com"))
            and parsed.path.startswith("/jobs/"))


def _unanswered_required(fields: list[dict]) -> bool:
    counts = group_counts(fields)
    for field in fields:
        if not field.get("required"):
            continue
        group = [field]
        if field.get("kind") == "checkbox":
            group = [f for f in fields if f.get("kind") == "checkbox"
                     and group_key(f, counts) == group_key(field, counts)]
        elif field.get("kind") == "radio":
            group = [f for f in fields if f.get("kind") == field.get("kind")
                     and (f.get("name") or f.get("question"))
                     == (field.get("name") or field.get("question"))]
        if not any(_control_already_answered(f) for f in group):
            return True
    return False


# Recheck the exact marked control and native validity immediately before clicking.
_READY_QUERY = r"""() => {
  // __APPLY_ROOT__
  const root = findApplyRoot();
  const label = (this.innerText || this.getAttribute('aria-label') || '')
    .replace(/\s+/g, ' ').trim().toLowerCase();
  let visible = !!this.getClientRects().length;
  for (let node = this; node; node = node.parentElement) {
    const css = getComputedStyle(node);
    if (css.display === 'none' || css.visibility === 'hidden' || css.opacity === '0') {
      visible = false;
    }
  }
  return JSON.stringify({
    ready: !!root && root.contains(this) && visible && !this.disabled
      && this.getAttribute('aria-disabled') !== 'true'
      && /^(?:submit|submit (?:your )?application)$/.test(label),
    invalid: !!root && Array.from(root.querySelectorAll('input,select,textarea'))
      .some(el => el.willValidate && !el.validity.valid)
  });
}""".replace("// __APPLY_ROOT__", FIND_APPLY_ROOT_JS)


async def _prepare_submit(page, outcome: Task4Outcome, title: str, company: str):
    if outcome.validation.issues or outcome.validation.skipped:
        return None, None, "this application has unresolved validation errors"
    reason = fill_failure_reason(outcome)
    if reason:
        return None, None, reason
    if outcome.submission_attempted:
        return None, None, "submission was already attempted; review the result manually"
    return await inspect_submit_control(page, title, company)


async def inspect_submit_control(page, title: str = "", company: str = ""):
    """Inspect current terminal controls without clicking or claiming the walk finished."""
    opened, _, fields, _ = await read_form(page)
    if not opened:
        return None, None, "the Easy Apply form is no longer open"
    if _unanswered_required(fields):
        return None, None, "required answers are unresolved on the current step"
    if await read_rejections(page, fields):
        return None, None, "the current form has validation errors"
    buttons = await read_form_buttons(page)
    candidates = [b for b in buttons if b.get("text", "").strip().lower() in _SUBMIT_LABELS]
    if (len(candidates) != 1 or candidates[0].get("disabled")
            or any(looks_like_next(b.get("text", "")) for b in buttons)):
        return None, None, "no single enabled terminal Submit application control was found"
    element = await _marker_element(page, "data-autojob-btn", candidates[0]["marker"])
    if element is None:
        return None, None, "the submit control disappeared"
    # browser-use computes click coordinates BEFORE its own scroll. Put the
    # button in view first so that scroll cannot invalidate the click point.
    await element.evaluate(
        "() => this.scrollIntoView({block:'center', inline:'nearest', behavior:'instant'})",
    )
    await asyncio.sleep(0.05)
    ready = _loads(await element.evaluate(_READY_QUERY))
    if not ready.get("ready") or ready.get("invalid"):
        return None, None, "the submit control or required form inputs are not ready"
    # Capture before clicking: an immediate confirmation must not become a stale baseline.
    initial = await _read_state(page, title, company)
    if initial is None:
        return None, None, "could not read the submission state"
    return element, initial, ""


async def _submit_on_page(
    page, outcome: Task4Outcome, settings: Settings, notify, title: str = "", company: str = "",
) -> AutoSubmitResult:
    """Drive one form. Kept separate so controlled browser fixtures use the real path."""
    initial, current = None, None
    try:
        element, initial, reason = await asyncio.wait_for(
            _prepare_submit(page, outcome, title, company), _READ_TIMEOUT,
        )
        if reason:
            return AutoSubmitResult("blocked", reason)
        notify("Task 22: submitting this completed application automatically.")
        emit_step(notify, "Submitting application - waiting for LinkedIn's confirmation...")
        outcome.submission_attempted = True
        await asyncio.wait_for(element.click(), _READ_TIMEOUT)
        deadline = time.monotonic() + settings.session.auto_submit_timeout_seconds
        while True:
            current = await _read_state(page, title, company)
            if current is None:
                reason = "the browser stopped responding after Submit"
                return AutoSubmitResult(
                    "unconfirmed", reason,
                    await capture_submission_failure(page, settings, reason, initial, current),
                )
            confirmation = current["confirmation"]
            if confirmation.strip().lower() == initial["confirmation"].strip().lower():
                confirmation = ""
            if submission_detected(
                confirmation=confirmation, form_open=current["form_open"],
                card_applied=current["card_applied"], card_was_applied=initial["card_applied"],
                status_submitted=current["status_submitted"],
                status_was_submitted=initial["status_submitted"],
            ):
                outcome.submitted = True
                with contextlib.suppress(Exception):
                    await _dismiss_confirmation(page, current, title)
                return AutoSubmitResult("submitted")
            if time.monotonic() >= deadline:
                reason = "LinkedIn did not confirm submission"
                return AutoSubmitResult(
                    "unconfirmed", reason,
                    await capture_submission_failure(page, settings, reason, initial, current),
                )
            await asyncio.sleep(min(settings.session.keep_open_poll_seconds,
                                    max(0, deadline - time.monotonic())))
    except Exception as exc:  # A click may reach the site even when CDP reports failure.
        status = "unconfirmed" if outcome.submission_attempted else "blocked"
        reason = "browser error; review this application manually"
        return AutoSubmitResult(status, reason, await capture_submission_failure(
            page, settings, reason, initial, current, error_type=type(exc).__name__,
        ))


async def submit_application(
    run_id: str, outcome: Task4Outcome, settings: Settings, progress=None,
    title: str = "", company: str = "",
) -> AutoSubmitResult:
    """Restrict automatic submission to LinkedIn jobs in the active run."""
    run = get_run(run_id)
    if run is None:
        return AutoSubmitResult("closed", "the browser session is no longer available")
    try:
        url = await asyncio.wait_for(run.page.get_url(), _READ_TIMEOUT)
        if not _is_linkedin_jobs_url(url):
            return AutoSubmitResult("blocked", "automatic submission supports LinkedIn jobs only")
    except Exception:
        return AutoSubmitResult("blocked", "could not verify the current site")
    return await _submit_on_page(run.page, outcome, settings, progress or print, title, company)
