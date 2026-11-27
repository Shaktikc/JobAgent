"""Best-effort live-page evidence for a crash bundle (Task 33).

Reuses the self-healing snapshot/screenshot helpers (BUG-048: screenshot
``run.page``, not the active tab). Every step is bounded by a short timeout and
suppressed, so a dead CDP connection can never hide the original crash. The
browser package is only consulted when it is already imported — a crash path
never imports browser-use.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from src.tools.crash_logs.redact import Clipper

PAGE_TIMEOUT_SECONDS = 5.0
MAX_DOM = 60_000
MAX_CONSOLE = 80
MAX_PAGE_TEXT = 12_000


def _live_run(run_id: str):
    """``(run_id, run)`` for the state's run, else the most recent live run."""
    module = sys.modules.get("src.tools.browser")
    if module is None:
        return run_id, None
    runs = getattr(module, "_ACTIVE_RUNS", None) or {}
    if run_id and run_id in runs:
        return run_id, runs[run_id]
    if runs:
        last = list(runs)[-1]
        return last, runs[last]
    return run_id, None


def page_available(run_id: str) -> bool:
    return _live_run(run_id)[1] is not None


async def _snapshot(run, bundle: Path) -> tuple[dict, str]:
    from src.tools.self_healing.capture import _page_snapshot, _take_screenshot

    snapshot = await _page_snapshot(run.page)
    screenshot = await _take_screenshot(run, bundle / "screenshot.png")
    return snapshot or {}, screenshot


async def capture_page(run_id: str, bundle: Path, clipper: Clipper) -> dict:
    """Write screenshot/DOM/text/console files; return the ``browser`` section."""
    resolved, run = _live_run(run_id)
    info = {
        "run_id": resolved or "",
        "page_url": "",
        "page_title": "",
        "screenshot": "",
        "dom": "",
        "page_text": "",
        "console": "",
        "error": "",
    }
    if run is None:
        info["error"] = "no live browser page"
        return info
    try:
        snapshot, screenshot = await asyncio.wait_for(
            _snapshot(run, bundle), timeout=PAGE_TIMEOUT_SECONDS
        )
    except Exception as exc:  # noqa: BLE001 - incl. TimeoutError; never mask the crash
        info["error"] = f"page snapshot failed: {type(exc).__name__}: {exc}"[:500]
        return info
    if not snapshot and not screenshot:
        info["error"] = "page snapshot returned nothing (page closed or CDP lost)"
    info["page_url"] = clipper.text(str(snapshot.get("url") or ""), "browser.page_url")
    info["page_title"] = clipper.text(str(snapshot.get("title") or ""), "browser.page_title")
    if screenshot:
        info["screenshot"] = "screenshot.png"
    files = {
        "dom": ("dom.html", str(snapshot.get("dom_excerpt") or ""), MAX_DOM),
        "page_text": ("page.txt", str(snapshot.get("visible_text") or ""), MAX_PAGE_TEXT),
    }
    for key, (name, text, limit) in files.items():
        if not text:
            continue
        (bundle / name).write_text(clipper.text(text, name, limit), encoding="utf-8")
        info[key] = name
    console = [str(line) for line in snapshot.get("console") or []]
    if len(console) > MAX_CONSOLE:
        clipper.note(f"console.log clipped from {len(console)} to the last {MAX_CONSOLE} lines")
        console = console[-MAX_CONSOLE:]
    if console:
        lines = [clipper.text(line, "console.log") for line in console]
        (bundle / "console.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        info["console"] = "console.log"
    return info


__all__ = ["capture_page", "page_available"]
