"""Atomic JSON-array storage preserving unreadable journals for inspection."""

import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

_LOCK = threading.Lock()


def append_discard(path: Path, record: dict, notify=None) -> None:
    """Append under a thread lock; callers handle write failures best-effort."""
    # Validate before touching the existing journal.
    json.dumps(record, ensure_ascii=False, allow_nan=False)
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        records = []
        if path.exists():
            try:
                records = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(records, list) or any(
                    not isinstance(row, dict) for row in records
                ):
                    raise ValueError("expected array of objects")
            except (ValueError, UnicodeError):
                stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
                backup = path.with_name(
                    f"{path.stem}.corrupt-{stamp}-{uuid4().hex}.json"
                )
                path.rename(backup)
                records = []
                if notify:
                    try:
                        notify(f"Task 29: unreadable discard log preserved at {backup}")
                    except Exception:
                        pass
        records.append(record)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=path.name, delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(records, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
