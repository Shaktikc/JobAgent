"""Task 29 journal preserves records and quarantines corrupt documents."""

import json

import pytest

from src.tools.linkedin_discard_log.store import append_discard


def test_append_preserves_first_record(tmp_path):
    path = tmp_path / "discard_log.json"
    first = {"reason": "invalid_input", "form": {"value": "日本語"}}
    append_discard(path, first)
    append_discard(path, {"reason": "leftover_form"})
    assert json.loads(path.read_text(encoding="utf-8")) == [
        first, {"reason": "leftover_form"},
    ]
    assert path.read_bytes().endswith(b"\n")


@pytest.mark.parametrize("original", [b"broken", b"{}", b"[1]", b"\xff"])
def test_corrupt_document_preserved(tmp_path, original):
    path = tmp_path / "discard_log.json"
    path.write_bytes(original)
    messages = []
    append_discard(path, {"reason": "test"}, notify=messages.append)
    assert json.loads(path.read_text()) == [{"reason": "test"}]
    backups = list(tmp_path.glob("discard_log.corrupt-*.json"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    assert messages
