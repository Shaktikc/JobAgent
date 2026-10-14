"""Task 3: describe the pool, let the LLM pick, and the 3.1 no-match fallback.

These tests inject a fake LLM (``describer`` / ``matcher``) and a fake human
(``asker``), so no browser or network is needed.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

from src.configuration import SessionSettings, Settings
from src.state import JobDescription
from src.tools.linkedin_best_matching_resume import ask_human_for_resume, ensure_resume
from src.tools.resume_descriptions import (
    ResumeDescription,
    ResumeDescriptionError,
    ResumeMatch,
    description_for,
    load_descriptions,
)
from src.tools.resume_library import load_library, remember_resume


def _settings(tmp_path: Path, **session) -> Settings:
    return Settings(
        session=SessionSettings(**session),
        data_dir=tmp_path,
        resumes_dir=tmp_path,
        resume_library_path=tmp_path / "resume_library.json",
        resume_descriptions_path=tmp_path / "resume_descriptions.json",
    )


def _asker(name: str, content: bytes):
    async def asker(page, settings, notify):
        return name, content

    return asker


def _describer(summary: str = "profile", *, error: str = ""):
    async def describe(path):
        if error:
            raise ResumeDescriptionError(error)
        return ResumeDescription(summary=summary)

    return describe


def _picks_first(rationale: str = "best fit"):
    async def pick(job_description, candidates):
        return ResumeMatch(
            selected_path=candidates[0][0] if candidates else None, rationale=rationale
        )

    return pick


def _picks_none(rationale: str = "nothing fits"):
    async def pick(job_description, candidates):
        return ResumeMatch(rationale=rationale)

    return pick


# --- the LLM match path -----------------------------------------------------


async def test_ensure_resume_returns_the_llm_match(tmp_path) -> None:
    (tmp_path / "python.txt").write_text("Python AWS Docker", encoding="utf-8")

    outcome = await ensure_resume(
        JobDescription(title="Python Engineer", body="Python AWS"),
        tmp_path,
        _settings(tmp_path),
        describer=_describer(),
        matcher=_picks_first("the LLM's reason"),
    )

    assert outcome.no_match is False
    assert outcome.selected_path.endswith("python.txt")
    assert outcome.rationale == "the LLM's reason"
    assert len(outcome.candidates) == 1
    assert outcome.candidates[0].described is True


async def test_ensure_resume_reports_a_describe_error(tmp_path) -> None:
    (tmp_path / "python.txt").write_text("Python", encoding="utf-8")

    outcome = await ensure_resume(
        JobDescription(title="Python Engineer", body="Python"),
        tmp_path,
        _settings(tmp_path),
        describer=_describer(error="the LLM call failed: boom"),
        matcher=_picks_first(),
    )

    assert outcome.error
    assert outcome.selected_path is None


async def test_ensure_resume_reports_a_match_error(tmp_path) -> None:
    (tmp_path / "python.txt").write_text("Python", encoding="utf-8")

    async def failing_pick(job_description, candidates):
        raise ResumeDescriptionError("the LLM call failed: boom")

    outcome = await ensure_resume(
        JobDescription(title="Python Engineer", body="Python"),
        tmp_path,
        _settings(tmp_path),
        describer=_describer(),
        matcher=failing_pick,
    )

    assert outcome.error
    assert outcome.selected_path is None


# --- the Task 3.1 no-match fallback ----------------------------------------


async def test_ensure_resume_stores_describes_and_remembers_a_human_resume(tmp_path) -> None:
    (tmp_path / "pastry.txt").write_text("pastry chef, baking", encoding="utf-8")
    settings = _settings(tmp_path)
    described: list[str] = []

    async def describe(path):
        described.append(str(path))
        return ResumeDescription(summary="senior python engineer")

    outcome = await ensure_resume(
        JobDescription(title="Senior Python Engineer", body="Python AWS Docker"),
        tmp_path,
        settings,
        page=object(),
        asker=_asker("My Resume.txt", b"Senior Python engineer, AWS Docker, 8 years"),
        describer=describe,
        matcher=_picks_none(),
    )

    assert outcome.no_match is True
    assert outcome.asked_human is True
    assert outcome.human_resume_path
    stored = Path(outcome.human_resume_path)
    assert stored.name == "My Resume.txt"
    assert stored.read_bytes() == b"Senior Python engineer, AWS Docker, 8 years"
    assert outcome.selected_path == str(stored)
    # The uploaded resume is described before it is used.
    assert str(stored) in described
    entries = load_descriptions(settings.resume_descriptions_file)
    assert description_for(entries, stored).summary == "senior python engineer"
    library = load_library(settings.resume_library_file)
    assert library and library[0]["resume"] == str(stored)


async def test_ensure_resume_reports_a_describe_error_for_the_upload(tmp_path) -> None:
    (tmp_path / "pastry.txt").write_text("pastry chef", encoding="utf-8")

    async def describe(path):
        if Path(path).name == "My Resume.txt":
            raise ResumeDescriptionError("the LLM call failed: boom")
        return ResumeDescription(summary="pool profile")

    outcome = await ensure_resume(
        JobDescription(title="Python Engineer", body="Python AWS"),
        tmp_path,
        _settings(tmp_path),
        page=object(),
        asker=_asker("My Resume.txt", b"Python engineer"),
        describer=describe,
        matcher=_picks_none(),
    )

    assert outcome.error
    assert outcome.selected_path is None
    # The file is stored, but never used without a description.
    assert (tmp_path / "My Resume.txt").exists()


async def test_ensure_resume_reuses_a_remembered_resume(tmp_path) -> None:
    (tmp_path / "pastry.txt").write_text("pastry chef, baking", encoding="utf-8")
    remembered = tmp_path / "cloud.txt"
    remembered.write_text("pastry chef, baking", encoding="utf-8")  # shares no job skill
    settings = _settings(tmp_path)
    remember_resume(
        settings.resume_library_file,
        JobDescription(title="Senior Cloud Engineer", body="AWS Kubernetes Terraform"),
        str(remembered),
    )

    outcome = await ensure_resume(
        JobDescription(title="Senior Cloud Engineer", body="AWS Kubernetes Terraform Docker"),
        tmp_path,
        settings,
        describer=_describer(),
        matcher=_picks_none(),
    )

    assert outcome.no_match is True
    assert outcome.reused_from_library == str(remembered)
    assert outcome.selected_path == str(remembered)
    assert outcome.asked_human is False


async def test_ensure_resume_without_page_leaves_it_unselected(tmp_path) -> None:
    (tmp_path / "pastry.txt").write_text("pastry chef", encoding="utf-8")

    outcome = await ensure_resume(
        JobDescription(title="Python Engineer", body="Python AWS"),
        tmp_path,
        _settings(tmp_path),
        describer=_describer(),
        matcher=_picks_none(),
    )

    assert outcome.no_match is True
    assert outcome.selected_path is None
    assert outcome.asked_human is False
    assert "no resume matched" in outcome.notes


async def test_ensure_resume_notes_when_the_human_skips(tmp_path) -> None:
    (tmp_path / "pastry.txt").write_text("pastry chef", encoding="utf-8")

    async def skip(page, settings, notify):
        return None

    outcome = await ensure_resume(
        JobDescription(title="Python Engineer", body="Python AWS"),
        tmp_path,
        _settings(tmp_path),
        page=object(),
        asker=skip,
        describer=_describer(),
        matcher=_picks_none(),
    )

    assert outcome.asked_human is True
    assert outcome.selected_path is None
    assert "did not provide" in outcome.notes


async def test_ensure_resume_notes_an_unstorable_upload(tmp_path) -> None:
    (tmp_path / "pastry.txt").write_text("pastry chef", encoding="utf-8")

    outcome = await ensure_resume(
        JobDescription(title="Python Engineer", body="Python AWS"),
        tmp_path,
        _settings(tmp_path),
        page=object(),
        asker=_asker("resume.exe", b"not a resume"),
        describer=_describer(),
        matcher=_picks_none(),
    )

    assert outcome.selected_path is None
    assert "could not store" in outcome.notes


async def test_ensure_resume_with_an_empty_pool_is_a_no_match(tmp_path) -> None:
    # No resumes at all: the LLM has nothing to pick, so it is a no-match that
    # falls through to Task 3.1 (which asks the human when a page is available).
    outcome = await ensure_resume(
        JobDescription(title="Python Engineer", body="Python AWS"),
        tmp_path,
        _settings(tmp_path),
        describer=_describer(),
        matcher=_picks_first(),
    )

    assert outcome.resumes_found == 0
    assert outcome.no_match is True
    assert outcome.selected_path is None


# --- the browser banner (unchanged Task 3.1 UI) -----------------------------


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
