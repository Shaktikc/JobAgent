"""Durable crash-bundle and ``index.json`` writes (Task 33).

Bundles are created fresh (never overwritten) and every file is written with the
Task 20 journal's atomic temp-file + fsync + ``os.replace`` pattern. The index is
append-only; an unreadable index is quarantined, never deleted.
"""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.tools.linkedin_validation.journal import write_atomic

INDEX_NAME = "index.json"
MAX_STATE_BYTES = 2 * 1024 * 1024
_INDEX_LOCK = threading.Lock()


def new_crash_id(now: datetime) -> str:
    return f"{now.strftime('%Y%m%d-%H%M%S-%f')}-{uuid.uuid4().hex[:8]}"


def reserve_bundle(crash_dir: Path, crash_id: str) -> tuple[str, Path]:
    """Create a brand-new bundle directory, suffixing the id on a collision."""
    crash_dir.mkdir(parents=True, exist_ok=True)
    candidate = crash_id
    for attempt in range(100):
        bundle = crash_dir / candidate
        try:
            bundle.mkdir()
            return candidate, bundle
        except FileExistsError:
            candidate = f"{crash_id}-{attempt + 1}"
    raise FileExistsError(f"could not reserve a crash bundle for {crash_id}")


def dumps(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n"


def clip_state_json(state: dict, notes: list[str]) -> str:
    """``state.json`` text, bounded to 2 MB."""
    text = dumps(state)
    size = len(text.encode("utf-8"))
    if size <= MAX_STATE_BYTES:
        return text
    notes.append(f"state.json clipped from {size} bytes to {MAX_STATE_BYTES} bytes")
    clipped = text.encode("utf-8")[:MAX_STATE_BYTES].decode("utf-8", errors="ignore")
    return dumps({"truncated": True, "original_bytes": size, "partial_json": clipped})


def write_files(bundle: Path, files: dict[str, str | bytes]) -> None:
    for name, data in files.items():
        write_atomic(bundle / name, data)


def append_index(crash_dir: Path, row: dict) -> Path | None:
    """Append ``row``; quarantine a corrupt index first. Returns the quarantine path."""
    path = crash_dir / INDEX_NAME
    quarantined = None
    with _INDEX_LOCK:
        rows: list = []
        if path.exists():
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(rows, list):
                    raise ValueError("index is not a JSON array")
            except (OSError, ValueError):
                stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
                quarantined = crash_dir / f"index.corrupt-{stamp}.json"
                path.replace(quarantined)
                rows = []
        rows.append(row)
        write_atomic(path, dumps(rows))
    return quarantined


def prune(crash_dir: Path, *, max_bundles: int, max_days: int, keep: str) -> list[str]:
    """Delete old bundles only when a positive limit is set; never ``keep``."""
    if max_bundles <= 0 and max_days <= 0:
        return []
    bundles = sorted(
        (path for path in crash_dir.iterdir() if path.is_dir() and path.name != keep),
        key=lambda path: path.name,
    )
    doomed: list[Path] = []
    if max_days > 0:
        cutoff = datetime.now(UTC) - timedelta(days=max_days)
        for path in bundles:
            try:
                stamp = datetime.strptime(path.name[:15], "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
            except ValueError:
                continue
            if stamp < cutoff:
                doomed.append(path)
    if max_bundles > 0:
        remaining = [path for path in bundles if path not in doomed]
        # ``keep`` counts toward the limit.
        excess = len(remaining) + 1 - max_bundles
        if excess > 0:
            doomed.extend(remaining[:excess])
    removed = []
    for path in doomed:
        shutil.rmtree(path, ignore_errors=True)
        removed.append(path.name)
    return removed


__all__ = [
    "INDEX_NAME",
    "append_index",
    "clip_state_json",
    "dumps",
    "new_crash_id",
    "prune",
    "reserve_bundle",
    "write_files",
]
