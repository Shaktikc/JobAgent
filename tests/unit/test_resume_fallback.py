"""Task 3.1: the no-match -> ask-the-human -> remember flow (no real browser)."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

from src.configuration import SessionSettings, Settings
from src.state import JobDescription
from src.tools.linkedin_best_matching_resume import (
    ask_human_for_resume,
    ensure_resume,
    no_match,
    select_best_resume,
)
from src.tools.resume_library import load_library, remember_resume


def _settings(tmp_path: Path, **session) -> Settings:
    return Settings(
        session=SessionSettings(**session),
        data_dir=tmp_path,
        resumes_dir=tmp_path,
        resume_library_path=tmp_path / "resume_library.json",
    )


def _asker(name: str, content: bytes):
    async def asker(page, settings, notify):
        return name, content

    return asker


def test_no_match_true_for_empty_pool(tmp_path) -> None:
    outcome = select_best_resume(JobDescription(title="Engineer", body="Python"), tmp_path)
    assert no_match(outcome, 0.0) is True


def test_ensure_resume_returns_a_normal_match(tmp_path) -> None:
    (tmp_path / "python.txt").write_text("Python AWS Docker", encoding="utf-8")

    outcome = asyncio.run(
        ensure_resume(
            JobDescription(title="Python Engineer", body="Python AWS"),
            tmp_path,
            _settings(tmp_path),
        )
    )

    assert outcome.no_match is False
    assert outcome.selected_path.endswith("python.txt")


def test_ensure_resume_stores_and_remembers_a_human_resume(tmp_path) -> None:
    (tmp_path / "pastry.txt").write_text("pastry chef, baking", encoding="utf-8")
    settings = _settings(tmp_path)

    outcome = asyncio.run(
        ensure_resume(
            JobDescription(title="Senior Python Engineer", body="Python AWS Docker"),
            tmp_path,
            settings,
            page=object(),
            asker=_asker("My Resume.txt", b"Senior Python engineer, AWS Docker, 8 years"),
        )
    )

    assert outcome.no_match is True
    assert outcome.asked_human is True
    assert outcome.human_resume_path
    stored = Path(outcome.human_resume_path)
    assert stored.name == "My Resume.txt"
    assert stored.read_bytes() == b"Senior Python engineer, AWS Docker, 8 years"
    assert outcome.selected_path == str(stored)
    entries = load_library(settings.resume_library_file)
    assert entries and entries[0]["resume"] == str(stored)


def test_ensure_resume_reuses_a_remembered_resume(tmp_path) -> None:
    (tmp_path / "pastry.txt").write_text("pastry chef, baking", encoding="utf-8")
    remembered = tmp_path / "cloud.txt"
    remembered.write_text("pastry chef, baking", encoding="utf-8")  # shares no job skill itself
    settings = _settings(tmp_path)
    remember_resume(
        settings.resume_library_file,
        JobDescription(title="Senior Cloud Engineer", body="AWS Kubernetes Terraform"),
        str(remembered),
    )

    outcome = asyncio.run(
        ensure_resume(
            JobDescription(title="Senior Cloud Engineer", body="AWS Kubernetes Terraform Docker"),
            tmp_path,
            settings,
        )
    )

    assert outcome.no_match is True
    assert outcome.reused_from_library == str(remembered)
    assert outcome.selected_path == str(remembered)
    assert outcome.asked_human is False


def test_ensure_resume_without_page_leaves_it_unselected(tmp_path) -> None:
    (tmp_path / "pastry.txt").write_text("pastry chef", encoding="utf-8")

    outcome = asyncio.run(
        ensure_resume(
            JobDescription(title="Python Engineer", body="Python AWS"),
            tmp_path,
            _settings(tmp_path),
        )
    )

    assert outcome.no_match is True
    assert outcome.selected_path is None
    assert outcome.asked_human is False
    assert "no resume matched" in outcome.notes


def test_ensure_resume_notes_when_the_human_skips(tmp_path) -> None:
    (tmp_path / "pastry.txt").write_text("pastry chef", encoding="utf-8")

    async def skip(page, settings, notify):
        return None

    outcome = asyncio.run(
        ensure_resume(
            JobDescription(title="Python Engineer", body="Python AWS"),
            tmp_path,
            _settings(tmp_path),
            page=object(),
            asker=skip,
        )
    )

    assert outcome.asked_human is True
    assert outcome.selected_path is None
    assert "did not provide" in outcome.notes


def test_ensure_resume_notes_an_unstorable_upload(tmp_path) -> None:
    (tmp_path / "pastry.txt").write_text("pastry chef", encoding="utf-8")

    outcome = asyncio.run(
        ensure_resume(
            JobDescription(title="Python Engineer", body="Python AWS"),
            tmp_path,
            _settings(tmp_path),
            page=object(),
            asker=_asker("resume.exe", b"not a resume"),
        )
    )

    assert outcome.selected_path is None
    assert "could not store" in outcome.notes


class _ResumeBannerPage:
    """A minimal page that plays Task 3.1's resume banner and file watcher."""

    def __init__(
        self,
        *,
        name: str = "resume.txt",
        content: bytes = b"Python AWS",
        done: bool = True,
        skip: bool = False,
        error: str = "",
    ) -> None:
        self.data = "data:application/octet-stream;base64," + base64.b64encode(content).decode()
        self.name = name
        self.done = done
        self.skip = skip
        self.error = error
        self.shown = False
        self.hidden = False

    async def evaluate(self, js: str, *args):
        if "autojob-resume" in js and "box.remove()" in js:
            self.hidden = True
            return True
        if "__autojobResumeFile" in js and "addEventListener" in js:
            return True
        if "__autojobResumeFile" in js:
            return json.dumps(
                {
                    "present": True,
                    "state": "skipped" if self.skip else "pending",
                    "done": self.done,
                    "name": self.name,
                    "data": self.data,
                    "error": self.error,
                }
            )
        if "autojob-resume" in js:
            if "getAttribute" in js:
                return json.dumps(
                    {"present": True, "state": "skipped" if self.skip else "pending"}
                )
            self.shown = True
            return True
        return ""


def test_ask_human_for_resume_returns_the_uploaded_file(tmp_path) -> None:
    page = _ResumeBannerPage(name="my resume.pdf", content=b"%PDF-1.4 hello")

    result = asyncio.run(
        ask_human_for_resume(page, _settings(tmp_path, ask_poll_seconds=0.01), lambda _m: None)
    )

    assert result == ("my resume.pdf", b"%PDF-1.4 hello")
    assert page.shown is True
    assert page.hidden is True


def test_ask_human_for_resume_read_error_returns_none(tmp_path) -> None:
    page = _ResumeBannerPage(error="could not read the file")

    result = asyncio.run(
        ask_human_for_resume(page, _settings(tmp_path, ask_poll_seconds=0.01), lambda _m: None)
    )

    assert result is None


def test_ask_human_for_resume_skip_returns_none(tmp_path) -> None:
    page = _ResumeBannerPage(skip=True)

    result = asyncio.run(
        ask_human_for_resume(page, _settings(tmp_path, ask_poll_seconds=0.01), lambda _m: None)
    )

    assert result is None
    assert page.hidden is True


def test_ask_human_for_resume_times_out(tmp_path) -> None:
    page = _ResumeBannerPage(done=False)

    result = asyncio.run(
        ask_human_for_resume(
            page,
            _settings(tmp_path, ask_timeout_seconds=0.05, ask_poll_seconds=0.01),
            lambda _m: None,
        )
    )

    assert result is None
    assert page.hidden is True
