"""Unit tests for resume discovery and text extraction (no browser)."""

from __future__ import annotations

import zipfile

import pytest

from src.tools import linkedin_best_matching_resume as resumes_tools
from src.tools.linkedin_best_matching_resume import (
    RESUME_SUFFIXES,
    extract_resume_text,
    list_resume_files,
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


@pytest.mark.parametrize("name", ["resume.txt", "resume.md"])
def test_supported_text_formats_round_trip(tmp_path, name) -> None:
    path = tmp_path / name
    path.write_text("Python, AWS, Docker", encoding="utf-8")
    assert "Python" in extract_resume_text(path)
