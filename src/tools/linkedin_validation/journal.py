"""Durable JSON-array journal; never discard an existing unreadable log."""

import json
import os
import tempfile
import threading
from pathlib import Path

_LOCK = threading.Lock()


def append_skip(path: Path, record: dict) -> None:
    """Atomically replace a journal after flushing the new complete document."""
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        records = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
            raise ValueError("invalid-input journal must contain a JSON array of objects")
        records.append(record)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=path.name,
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(records, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
