"""Durable JSON-array journal; never discard an existing unreadable log."""

import json
import os
import tempfile
import threading
from pathlib import Path

_LOCK = threading.Lock()


def write_atomic(path: Path, data: str | bytes) -> None:
    """Write ``data`` to a same-directory temp file, fsync, then ``os.replace``.

    Shared by the Task 20 journal and the Task 33 crash-log store. An interrupted
    replace leaves the previous file untouched and removes the temp file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    binary = isinstance(data, bytes)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb" if binary else "w",
            encoding=None if binary else "utf-8",
            dir=path.parent,
            prefix=path.name,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def append_skip(path: Path, record: dict) -> None:
    """Atomically replace a journal after flushing the new complete document."""
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        records = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
            raise ValueError("invalid-input journal must contain a JSON array of objects")
        records.append(record)
        write_atomic(path, json.dumps(records, indent=2, ensure_ascii=False) + "\n")
