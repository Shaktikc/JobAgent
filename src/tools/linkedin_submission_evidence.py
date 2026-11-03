"""Preserve submission failures without storing application answers in JSON."""

import asyncio
import base64
import contextlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from src.tools.browser import FIND_APPLY_ROOT_JS, _loads

_DIAGNOSTICS = r"""() => {
  // __APPLY_ROOT__
  const root = findApplyRoot();
  const buttons = root ? Array.from(root.querySelectorAll('button')).map(el => {
    const rect = el.getBoundingClientRect();
    const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2;
    const hit = document.elementFromPoint(x, y);
    return {label:(el.innerText || el.getAttribute('aria-label') || '').trim(),
      disabled:el.disabled || el.getAttribute('aria-disabled') === 'true',
      top:rect.top,left:rect.left,width:rect.width,height:rect.height,
      receives_pointer:!!hit && (hit === el || el.contains(hit))};
  }) : [];
  return JSON.stringify({form_found:!!root,buttons:buttons,
    viewport:{width:innerWidth,height:innerHeight},
    recent_requests:performance.getEntriesByType('resource').slice(-12).map(entry => {
      const url = new URL(entry.name,location.href);
      return {host:url.hostname,path:url.pathname,status:entry.responseStatus || null};
    })
  });
}""".replace("// __APPLY_ROOT__", FIND_APPLY_ROOT_JS)


def _signals(state):
    return {key: bool((state or {}).get(key)) for key in (
        "form_open", "card_applied", "status_submitted", "confirmation",
    )}


async def capture_submission_failure(page, settings, reason, initial=None, current=None,
                                     error_type="") -> str:
    """Best effort; evidence collection never retries or changes the application."""
    folder = settings.debug_dir / "task22"
    name = datetime.now(UTC).strftime("unconfirmed-%Y%m%d-%H%M%S-") + uuid4().hex[:6]
    report = {"reason": reason, "error_type": error_type,
              "before": _signals(initial), "after": _signals(current)}
    with contextlib.suppress(Exception):
        report["dom"] = _loads(await asyncio.wait_for(page.evaluate(_DIAGNOSTICS), 3))
    with contextlib.suppress(Exception):
        folder.mkdir(parents=True, exist_ok=True)
        screenshot = await asyncio.wait_for(page.screenshot(), 5)
        (folder / f"{name}.png").write_bytes(base64.b64decode(screenshot))
        report["screenshot"] = f"{name}.png"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return str(path)
    except OSError:
        return ""
