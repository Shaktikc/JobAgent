"""Capture forensic evidence when the Easy Apply walk hits a hard stop.

The bundle is written **before** the browser is closed, so the screenshot and DOM
show the exact state that failed. The screenshot and DOM are best-effort: a dead
CDP connection must never hide the original exception.
"""

from __future__ import annotations

import base64
import contextlib
import json
import sys
import traceback as traceback_module
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.configuration import Settings
from src.tools.self_healing.fingerprint import (
    classify_failure,
    failure_fingerprint,
    symptom_for,
)
from src.tools.self_healing.models import CapturedFailure, FailureEvidence, JobTarget

_CONSOLE_INSTALL_JS = r"""
() => {
  if (window.__autojobConsoleInstalled) return true;
  window.__autojobConsoleInstalled = true;
  window.__autojobConsole = window.__autojobConsole || [];
  const push = (level, args) => {
    try {
      const text = Array.from(args).map((value) => {
        if (typeof value === 'string') return value;
        try { return JSON.stringify(value); } catch (err) { return String(value); }
      }).join(' ');
      window.__autojobConsole.push(level + ': ' + text);
      if (window.__autojobConsole.length > 80) window.__autojobConsole.shift();
    } catch (err) {}
  };
  ['error', 'warn'].forEach((level) => {
    const original = console[level];
    console[level] = function (...args) {
      push(level, args);
      return original.apply(console, args);
    };
  });
  window.addEventListener('error', (event) => {
    push('error', [event.message || 'window error']);
  });
  window.addEventListener('unhandledrejection', (event) => {
    push('error', ['unhandled rejection: ' + String(event.reason || '')]);
  });
  return true;
}
"""

_PAGE_SNAPSHOT_JS_TEMPLATE = (
    "() => {\n"
    + "__FIND_APPLY_ROOT_JS__\n"
    + r"""
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  let root = null;
  try { root = findApplyRoot(); } catch (err) { root = null; }
  const text = norm(root ? root.innerText : document.body.innerText);
  const dom = root ? root.outerHTML : document.body.outerHTML;
  return JSON.stringify({
    url: location.href,
    title: document.title || '',
    ready_state: document.readyState || '',
    form_open: !!root,
    visible_text: text.slice(0, 12000),
    dom_excerpt: (dom || '').slice(0, 60000),
    console: Array.isArray(window.__autojobConsole)
      ? window.__autojobConsole.slice(-80) : []
  });
}
"""
)


async def install_console_capture(run_id: str | None) -> bool:
    """Install an in-page console/error buffer for later failure capture.

    Called before the fill starts; failures that happen later in the same page can
    then include the browser's recent error/warning lines. Missing sessions and
    old pages are ignored.
    """
    if not run_id:
        return False
    from src.tools.browser import _safe, get_run

    run = get_run(run_id)
    if run is None:
        return False
    return bool(await _safe(run.page.evaluate(_CONSOLE_INSTALL_JS), False))


async def _read_structured_form(page) -> tuple[str, str, list[dict], list[dict], dict]:
    """Read the live form's step, fields, buttons, and resume controls."""
    from src.tools.linkedin_easy_apply_fill import (
        read_form,
        read_form_buttons,
        read_resume_info,
    )

    step = ""
    title = ""
    fields: list[dict] = []
    buttons: list[dict] = []
    resume: dict = {}
    with contextlib.suppress(Exception):
        opened, title, fields, step = await read_form(page)
        if not opened:
            step = ""
    with contextlib.suppress(Exception):
        buttons = await read_form_buttons(page)
    with contextlib.suppress(Exception):
        resume = await read_resume_info(page)
    return step, title, list(fields or []), list(buttons or []), dict(resume or {})


async def _page_snapshot(page) -> dict:
    from src.tools.browser import FIND_APPLY_ROOT_JS, _loads, _safe

    js = _PAGE_SNAPSHOT_JS_TEMPLATE.replace("__FIND_APPLY_ROOT_JS__", FIND_APPLY_ROOT_JS)
    return _loads(await _safe(page.evaluate(js), ""))


async def _take_screenshot(run, path: Path) -> str:
    """Write a screenshot of the **failing page**, not the active tab.

    ``session.take_screenshot`` targets whichever tab Chromium currently has
    active; a run can have another page/tab in front, which produced a misleading
    black/loading screenshot for BUG-048. Capture ``run.page`` directly first, and
    fall back to the session only when the page-level CDP call is unavailable.
    """
    page_shot = getattr(run.page, "screenshot", None)
    if callable(page_shot):
        with contextlib.suppress(Exception):
            encoded = await page_shot(format="png")
            if encoded:
                path.write_bytes(base64.b64decode(encoded))
                if path.is_file():
                    return str(path)
    take = getattr(run.session, "take_screenshot", None)
    if take is None:
        return ""
    with contextlib.suppress(Exception):
        await take(path=str(path), full_page=True)
    return str(path) if path.is_file() else ""


def _format_traceback(traceback_text: str) -> str:
    """Use the supplied traceback, else the active exception's traceback."""
    if traceback_text:
        return traceback_text
    if sys.exc_info()[0] is not None:
        return traceback_module.format_exc()
    return ""


def _task_fields(task4: Any) -> list[dict]:
    fields = getattr(task4, "fields", None) if task4 is not None else None
    if not fields:
        return []
    result: list[dict] = []
    for field in fields:
        if hasattr(field, "model_dump"):
            result.append(field.model_dump())
        elif isinstance(field, dict):
            result.append(dict(field))
    return result


def _write_report(bundle: Path, evidence: FailureEvidence, task4: Any) -> None:
    lines = [
        "# Auto-recorded Easy Apply failure",
        "",
        f"- **Category:** {evidence.category}",
        f"- **Stage:** {evidence.stage}",
        f"- **Captured:** {evidence.captured_at}",
        f"- **Job title:** {evidence.job_title or '(unknown)'}",
        f"- **Company:** {evidence.company or '(unknown)'}",
        f"- **Job URL:** {evidence.job_url or '(unknown)'}",
        f"- **Page URL:** {evidence.page_url or '(unknown)'}",
        f"- **Page title:** {evidence.page_title or '(unknown)'}",
        f"- **Step:** {evidence.step or '(unknown)'}",
        f"- **Step title:** {evidence.step_title or '(unknown)'}",
        f"- **Run id:** {evidence.run_id or '(unknown)'}",
        f"- **Screenshot:** {evidence.screenshot_path or '(not captured)'}",
        "",
        "## Symptom",
        "",
        evidence.error or "(no exception message)",
        "",
        "## Task 4 notes",
        "",
        evidence.notes or "(none)",
        "",
        "## Fields",
        "",
        "```json",
        json.dumps(evidence.fields, indent=2, default=str),
        "```",
        "",
        "## Buttons",
        "",
        "```json",
        json.dumps(evidence.buttons, indent=2, default=str),
        "```",
        "",
        "## Resume controls",
        "",
        "```json",
        json.dumps(evidence.resume, indent=2, default=str),
        "```",
        "",
        "## Recent browser console",
        "",
    ]
    lines.extend(evidence.console or ["(none captured)"])
    lines += [
        "",
        "## Traceback",
        "",
        "```",
        evidence.traceback or "(none)",
        "```",
        "",
        "## Evidence files",
        "",
        "- `failure.json` - the structured evidence",
        "- `dom.html` - the failing form's DOM excerpt",
        "- `page.txt` - the visible page text",
        "- `console.log` - browser console/error lines",
        "- `screenshot.png` - when capture succeeded",
        "",
    ]
    if task4 is not None and getattr(task4, "notes", ""):
        lines.append(f"_Task 4 outcome status: {task4.notes}_")
    (bundle / "report.md").write_text("\n".join(lines), encoding="utf-8")


async def capture_failure(
    run_id: str | None,
    settings: Settings,
    *,
    stage: str = "fill",
    error: str = "",
    task4: Any = None,
    target: JobTarget | None = None,
    traceback_text: str = "",
) -> CapturedFailure:
    """Capture a failure bundle and return its fingerprint and evidence path."""
    target = target or JobTarget()
    from src.tools.browser import get_run

    run = get_run(run_id)
    step = ""
    step_title = ""
    fields: list[dict] = []
    buttons: list[dict] = []
    resume: dict = {}
    if run is not None:
        step, step_title, fields, buttons, resume = await _read_structured_form(run.page)
    if not fields:
        fields = _task_fields(task4)

    notes = getattr(task4, "notes", "") if task4 is not None else ""
    category = classify_failure(error, task4, notes, stage=stage)
    fingerprint = failure_fingerprint(category, error=error, task4=task4, step=step, fields=fields)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    bundle = settings.debug_dir / "self_healing" / f"{stamp}-{fingerprint[:12]}"
    bundle.mkdir(parents=True, exist_ok=True)

    snapshot: dict = {}
    screenshot_path = ""
    if run is not None:
        snapshot = await _page_snapshot(run.page)
        screenshot_path = await _take_screenshot(run, bundle / "screenshot.png")

    evidence = FailureEvidence(
        stage=stage,
        category=category,
        error=error or (f"Task 4: {notes}" if notes else ""),
        traceback=_format_traceback(traceback_text),
        job_title=target.title,
        company=target.company,
        job_url=target.url,
        page_url=str(snapshot.get("url") or ""),
        page_title=str(snapshot.get("title") or ""),
        step=step,
        step_title=step_title,
        notes=notes,
        fields=fields,
        buttons=buttons,
        resume=resume,
        visible_text=str(snapshot.get("visible_text") or ""),
        dom_excerpt=str(snapshot.get("dom_excerpt") or ""),
        console=[str(line) for line in snapshot.get("console") or []],
        screenshot_path=screenshot_path,
        captured_at=datetime.now(UTC).isoformat(),
        run_id=run_id or "",
    )
    # The page snapshot can reveal a form that the structured reader missed.
    if not evidence.page_url and run is not None:
        from src.tools.browser import _safe

        evidence.page_url = str(snapshot.get("url") or await _safe(run.page.get_url(), "") or "")

    (bundle / "failure.json").write_text(evidence.model_dump_json(indent=2), encoding="utf-8")
    (bundle / "dom.html").write_text(evidence.dom_excerpt, encoding="utf-8")
    (bundle / "page.txt").write_text(evidence.visible_text, encoding="utf-8")
    (bundle / "console.log").write_text("\n".join(evidence.console), encoding="utf-8")
    _write_report(bundle, evidence, task4)
    return CapturedFailure(
        fingerprint=fingerprint,
        category=category,
        symptom=symptom_for(category, task4, error),
        bundle_dir=str(bundle),
        evidence=evidence,
    )


__all__ = ["capture_failure", "install_console_capture"]
