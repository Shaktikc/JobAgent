"""Unit tests for resume discovery, extraction, and selection (no browser)."""

from __future__ import annotations

import os
import zipfile

import pytest

from src.state import JobDescription
from src.tools import resumes as resumes_tools
from src.tools.resumes import (
    RESUME_SUFFIXES,
    extract_resume_text,
    list_resume_files,
    select_best_resume,
)


def _make_docx(path, text: str) -> None:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)


def test_resume_suffixes_cover_supported_formats() -> None:
    assert set(RESUME_SUFFIXES) == {".pdf", ".docx", ".txt", ".md"}


def test_list_resume_files_filters_and_sorts(tmp_path) -> None:
    (tmp_path / "b_resume.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a_resume.md").write_text("a", encoding="utf-8")
    (tmp_path / "notes.exe").write_text("nope", encoding="utf-8")
    (tmp_path / "sub").mkdir()

    names = [path.name for path in list_resume_files(tmp_path)]
    assert names == ["a_resume.md", "b_resume.txt"]


def test_list_resume_files_missing_dir_is_empty(tmp_path) -> None:
    assert list_resume_files(tmp_path / "nope") == []


def test_extract_text_and_markdown(tmp_path) -> None:
    text_file = tmp_path / "resume.txt"
    text_file.write_text("Hello plain text", encoding="utf-8")
    markdown = tmp_path / "resume.md"
    markdown.write_text("# Title\nPython, AWS", encoding="utf-8")

    assert extract_resume_text(text_file) == "Hello plain text"
    assert "Python" in extract_resume_text(markdown)


def test_extract_docx_uses_stdlib(tmp_path) -> None:
    docx = tmp_path / "resume.docx"
    _make_docx(docx, "Python AWS engineer")

    assert "Python AWS engineer" in extract_resume_text(docx)


def test_extract_pdf_dispatches_to_pdf_reader(monkeypatch, tmp_path) -> None:
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(resumes_tools, "_extract_pdf", lambda _path: "PDF resume text")

    assert extract_resume_text(pdf) == "PDF resume text"


def test_extract_unknown_suffix_returns_empty(tmp_path) -> None:
    unknown = tmp_path / "resume.rtf"
    unknown.write_text("nope", encoding="utf-8")
    assert extract_resume_text(unknown) == ""


def test_select_best_resume_chooses_highest_score(tmp_path) -> None:
    (tmp_path / "python.txt").write_text(
        "Senior Python engineer. Python, AWS, Docker, 8 years.", encoding="utf-8"
    )
    (tmp_path / "frontend.txt").write_text(
        "Frontend developer. React, CSS, 2 years.", encoding="utf-8"
    )
    description = JobDescription(
        title="Senior Python Engineer",
        body="Python, AWS and Docker. 5+ years required.",
    )

    outcome = select_best_resume(description, tmp_path)

    assert outcome.resumes_found == 2
    assert len(outcome.candidates) == 2
    assert outcome.selected_path is not None
    assert outcome.selected_path.endswith("python.txt")
    assert outcome.rationale


def test_select_best_resume_empty_folder(tmp_path) -> None:
    outcome = select_best_resume(JobDescription(title="Engineer", body="Python"), tmp_path)

    assert outcome.resumes_found == 0
    assert outcome.selected_path is None
    assert "no resumes" in outcome.notes


def test_select_best_resume_tie_breaks_on_mtime(tmp_path) -> None:
    older = tmp_path / "older.txt"
    newer = tmp_path / "newer.txt"
    content = "Python AWS Docker"
    older.write_text(content, encoding="utf-8")
    newer.write_text(content, encoding="utf-8")
    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))

    outcome = select_best_resume(JobDescription(title="Engineer", body="Python AWS"), tmp_path)

    assert outcome.selected_path.endswith("newer.txt")
    assert outcome.tie_break
    assert "tie" in outcome.notes.lower()


def test_select_best_resume_handles_unreadable_file(tmp_path) -> None:
    good = tmp_path / "good.txt"
    good.write_text("Python AWS Docker engineer", encoding="utf-8")
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not really a pdf")

    outcome = select_best_resume(JobDescription(title="Engineer", body="Python AWS"), tmp_path)

    # The readable resume wins even though a corrupt file was also present.
    assert outcome.resumes_found == 2
    assert len(outcome.candidates) == 2
    assert outcome.selected_path.endswith("good.txt")
    assert "could not read" in outcome.notes


@pytest.mark.parametrize("name", ["resume.txt", "resume.md"])
def test_supported_text_formats_round_trip(tmp_path, name) -> None:
    path = tmp_path / name
    path.write_text("Python, AWS, Docker", encoding="utf-8")
    assert "Python" in extract_resume_text(path)
