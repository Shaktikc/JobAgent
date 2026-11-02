"""The validation journal must preserve links before a form is discarded."""

import json

import pytest

from src.tools.linkedin_validation.journal import append_skip


def test_journal_is_json_and_preserves_previous_runs(tmp_path):
    path = tmp_path / "skips.json"
    append_skip(path, {"job_url": "https://www.linkedin.com/jobs/view/123/"})
    append_skip(path, {"job_url": "https://www.linkedin.com/jobs/view/456/"})
    assert [row["job_url"] for row in json.loads(path.read_text())] == [
        "https://www.linkedin.com/jobs/view/123/",
        "https://www.linkedin.com/jobs/view/456/",
    ]


def test_interrupted_replace_keeps_existing_journal(tmp_path, monkeypatch):
    from src.tools.linkedin_validation import journal

    path = tmp_path / "skips.json"
    append_skip(path, {"job_url": "first"})
    before = path.read_bytes()

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(journal.os, "replace", fail)
    with pytest.raises(OSError, match="disk failure"):
        append_skip(path, {"job_url": "second"})
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("content", ["broken", "{}", '["bad entry"]'])
def test_corrupt_journal_is_never_overwritten(tmp_path, content):
    path = tmp_path / "skips.json"
    path.write_text(content)
    with pytest.raises(ValueError):
        append_skip(path, {"job_url": "new"})
    assert path.read_text() == content
