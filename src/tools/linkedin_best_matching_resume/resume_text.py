"""Task 3's resume discovery and text extraction.

Resume files are only ever read here; they are never renamed, moved, or modified.
PDF text comes from the optional ``pypdf`` dependency (imported lazily); DOCX uses
only the standard library.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

from src.tools.resume_library import RESUME_SUFFIXES

_DOCX_TEXT_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"


def list_resume_files(resumes_dir: str | Path) -> list[Path]:
    """Return the readable resume files in ``resumes_dir`` (sorted by name)."""
    directory = Path(resumes_dir)
    if not directory.is_dir():
        return []
    files = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in RESUME_SUFFIXES
    ]
    return sorted(files, key=lambda path: path.name.lower())


def extract_resume_text(path: str | Path) -> str:
    """Return the readable text of a resume file, or ``""`` for unknown formats."""
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return file_path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        return _extract_pdf(file_path)
    if suffix == ".docx":
        return _extract_docx(file_path)
    return ""


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader  # lazy: only needed for PDF resumes

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_docx(path: Path) -> str:
    """Extract text from a ``.docx`` using only the standard library."""
    try:
        with zipfile.ZipFile(path) as archive:
            document_xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile, OSError):
        return ""
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError:
        return ""
    return " ".join(node.text or "" for node in root.iter(_DOCX_TEXT_TAG))


__all__ = [
    "RESUME_SUFFIXES",
    "_extract_docx",
    "_extract_pdf",
    "extract_resume_text",
    "list_resume_files",
]
