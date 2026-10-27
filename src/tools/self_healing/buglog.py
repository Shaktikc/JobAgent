"""Record auto-captured Easy Apply failures in the repository bug log.

Failures are deduplicated by fingerprint: a repeat of the same broken step reuses
its `BUG-NNN` entry and increments its occurrence count instead of creating a new
bug every run. The entry is written before recovery is attempted, so a later crash
always has evidence on disk even if the process is killed.
"""

from __future__ import annotations

import contextlib
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path

from src.configuration import PROJECT_ROOT, Settings
from src.tools.self_healing.models import CapturedFailure, FailureRecord

_LOCK = threading.Lock()
_BUG_DIR = "known Bugs"
_BUG_FILE = "self_healing_bugs.md"
_INDEX_FILE = "bug_log.md"
_ID_RE = re.compile(r"BUG-(\d{3,})")
_ENTRY_RE = re.compile(r"### (BUG-\d+) — (?P<title>[^\n]*)\n(?P<body>.*?)(?=\n### |\Z)", re.S)
_FINGERPRINT_RE = re.compile(r"\*\*Failure fingerprint:\*\* `([0-9a-f]+)`", re.I)


def _bug_dir(root: Path) -> Path:
    return root / _BUG_DIR


def _bug_file(root: Path) -> Path:
    return _bug_dir(root) / _BUG_FILE


def _index_file(root: Path) -> Path:
    return _bug_dir(root) / _INDEX_FILE


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _next_bug_id(root: Path) -> str:
    highest = 0
    for path in _bug_dir(root).glob("*.md"):
        for match in _ID_RE.finditer(_read(path)):
            highest = max(highest, int(match.group(1)))
    return f"BUG-{highest + 1:03d}"


def _entry_by_fingerprint(text: str, fingerprint: str) -> tuple[str, str] | None:
    for match in _ENTRY_RE.finditer(text):
        body = match.group("body")
        found = _FINGERPRINT_RE.search(body)
        if found and found.group(1).lower() == fingerprint.lower():
            return match.group(1), match.group(0)
    return None


def _entry_by_id(text: str, bug_id: str) -> str | None:
    match = re.search(
        rf"### {re.escape(bug_id)} — [^\n]*\n.*?(?=\n### |\Z)",
        text,
        re.S,
    )
    return match.group(0) if match else None


def _update_index(
    root: Path,
    bug_id: str,
    symptom: str,
    status: str,
    fix: str,
    *,
    scope: str = "Self-Healing — fill",
) -> None:
    path = _index_file(root)
    text = _read(path)
    if not text:
        return
    row_re = re.compile(rf"^\| {re.escape(bug_id)} \|.*$", re.M)
    existing = row_re.search(text)
    if existing:
        cells = existing.group(0).split("|")
        if len(cells) >= 6:
            cells[4] = f" {status} "
            cells[5] = f" {fix} "
            text = text[: existing.start()] + "|".join(cells) + text[existing.end() :]
    else:
        row = f"| {bug_id} | {scope} | {symptom[:120]} | {status} | {fix} |"
        marker = "\n## Template for new entries"
        if marker in text:
            text = text.replace(marker, "\n" + row + "\n" + marker, 1)
        else:
            text = text.rstrip() + "\n" + row + "\n"
    _write_atomic(path, text)


# The stage a failure came from decides which area owns its index row, so a
# browse-stage stop is not filed under "fill" (BUG-065) and a ``next_job``
# pagination stop is not filed under "fill" either (BUG-068).
_SCOPE_BY_STAGE = {
    "browse": "Self-Healing — browse/search",
    "match": "Self-Healing — match/resume",
    "next_job": "Self-Healing — next job/pagination",
}


def _scope_for(stage: str) -> str:
    return _SCOPE_BY_STAGE.get((stage or "").strip().lower(), "Self-Healing — fill")


def _occurrences(body: str) -> int:
    match = re.search(r"\*\*Occurrences:\*\* (\d+)", body)
    return int(match.group(1)) if match else 1


def _touch_occurrence(body: str, captured: CapturedFailure) -> str:
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    count = _occurrences(body) + 1
    line = f"- **Occurrences:** {count} (last {stamp}; bundle `{captured.bundle_dir}`)"
    if re.search(r"\*\*Occurrences:\*\* [^\n]*", body):
        body = re.sub(
            r"\*\*Occurrences:\*\* [^\n]*",
            lambda _match: line,
            body,
            count=1,
        )
    else:
        body = body.rstrip() + "\n" + line + "\n"
    return body


def _open_reoccurrence(entry: str) -> str:
    entry = re.sub(
        r"- \*\*Status:\*\* .*",
        "- **Status:** 🔴 Open",
        entry,
        count=1,
    )
    entry = re.sub(
        r"- \*\*Fix:\*\* .*",
        "- **Fix:** Regression detected; pending analysis and a new fix.",
        entry,
        count=1,
    )
    return entry


def record_failure(
    captured: CapturedFailure,
    *,
    root: Path | None = None,
) -> FailureRecord:
    """Write (or update) the bug entry for ``captured`` and return its identity."""
    root = root or PROJECT_ROOT
    path = _bug_file(root)
    symptom = captured.symptom or captured.category.replace("_", " ")
    with _LOCK:
        text = _read(path)
        if not text:
            text = (
                "# Self-Healing Loop — Bugs (auto-recorded)\n\n"
                "Failures captured by the bounded Easy Apply self-healing loop. "
                "See [`bug_log.md`](bug_log.md) for the shared status markers.\n\n"
                "| ID | Symptom (short) | Status | Fix commit(s) |\n"
                "|----|-----------------|--------|---------------|\n"
            )
        existing = _entry_by_fingerprint(text, captured.fingerprint)
        if existing:
            bug_id, entry = existing
            title_match = re.match(r"### BUG-\d+ — ([^\n]*)", entry)
            title = title_match.group(1) if title_match else symptom
            entry = _touch_occurrence(entry, captured)
            entry = _open_reoccurrence(entry)
            text = text.replace(existing[1], entry, 1)
            _write_atomic(path, text)
            _update_index(
                root,
                bug_id,
                symptom,
                "🔴 Open",
                "(pending)",
                scope=_scope_for(captured.evidence.stage),
            )
            return FailureRecord(
                fingerprint=captured.fingerprint,
                category=captured.category,
                bug_id=bug_id,
                bug_path=str(path),
                bundle_dir=captured.bundle_dir,
                symptom=title or symptom,
                status="open",
                occurrences=_occurrences(entry),
                evidence=captured.evidence,
            )

        bug_id = _next_bug_id(root)
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        entry = (
            f"### {bug_id} — {symptom[:160]}\n\n"
            f"- **Symptom:** {captured.evidence.error or symptom}\n"
            f"- **Root cause:** Auto-classified as `{captured.category}` during "
            f"`{captured.evidence.stage}`; see the bundle for the failing step/DOM. "
            "A source-level root cause is still pending.\n"
            "- **Fix:** Pending. Recorded before any repair attempt.\n"
            "- **Status:** 🔴 Open\n"
            f"- **Evidence:** bundle `{captured.bundle_dir}`; "
            f"captured {captured.evidence.captured_at or stamp}\n"
            f"- **Failure fingerprint:** `{captured.fingerprint}`\n"
            f"- **Occurrences:** 1 (first {stamp})\n"
        )
        text = text.rstrip() + "\n\n" + entry
        _write_atomic(path, text)
        _update_index(
            root,
            bug_id,
            symptom,
            "🔴 Open",
            "(pending)",
            scope=_scope_for(captured.evidence.stage),
        )
        return FailureRecord(
            fingerprint=captured.fingerprint,
            category=captured.category,
            bug_id=bug_id,
            bug_path=str(path),
            bundle_dir=captured.bundle_dir,
            symptom=symptom,
            status="open",
            evidence=captured.evidence,
        )


def update_bug(
    bug_id: str,
    *,
    status: str,
    fix: str,
    evidence: str = "",
    note: str = "",
    root: Path | None = None,
) -> bool:
    """Update one bug entry's status/fix and keep the master index in sync."""
    root = root or PROJECT_ROOT
    path = _bug_file(root)
    with _LOCK:
        text = _read(path)
        entry = _entry_by_id(text, bug_id)
        if not entry:
            return False
        updated = re.sub(r"- \*\*Status:\*\* .*", f"- **Status:** {status}", entry, count=1)
        updated = re.sub(r"- \*\*Fix:\*\* .*", f"- **Fix:** {fix}", updated, count=1)
        if evidence:
            updated = updated.rstrip() + f"\n- **Recovery evidence:** {evidence}\n"
        if note:
            updated = updated.rstrip() + f"\n- **Note:** {note}\n"
        text = text.replace(entry, updated, 1)
        _write_atomic(path, text)
        symptom_match = re.search(r"### BUG-\d+ — ([^\n]*)", updated)
        _update_index(
            root,
            bug_id,
            symptom_match.group(1) if symptom_match else "",
            status,
            "(auto-recorded)",
        )
    return True


def _fix_text(settings: Settings) -> str:
    if (settings.self_healing.repair_command or "").strip():
        return (
            "Repair command completed and its tests passed; the same job was then "
            "reopened and filled."
        )
    return (
        "Automatic runtime recovery: the failed browser session was closed, the "
        "same job was reopened, and the fill succeeded without a source change."
    )


def mark_fixed(
    failures: list[FailureRecord],
    settings: Settings,
    *,
    root: Path,
    evidence: str,
) -> None:
    """Mark every recorded bug for a recovered fill as Fixed."""
    for record in failures:
        if not record.bug_id:
            continue
        with contextlib.suppress(Exception):
            update_bug(
                record.bug_id,
                status="🟢 Fixed",
                fix=_fix_text(settings),
                evidence=evidence,
                root=root,
            )


def mark_exhausted(failures: list[FailureRecord], root: Path, attempts: int) -> None:
    """Leave every recorded bug Open when the recovery attempts are exhausted."""
    for record in failures:
        if not record.bug_id:
            continue
        with contextlib.suppress(Exception):
            update_bug(
                record.bug_id,
                status="🔴 Open",
                fix="Self-healing attempts exhausted; evidence preserved for repair.",
                note=f"Stopped after {attempts} recovery attempt(s).",
                root=root,
            )


__all__ = ["mark_exhausted", "mark_fixed", "record_failure", "update_bug"]
