"""Task 3: read the open job's description and pick the best-matching resume.

This module owns Task 3 in full, gathered from the two places its code used to
live (the description reader in :mod:`src.tools.browser`, the resume selection in
``src.tools.resumes``):

1. Read the description of the job that is open in the details pane: title,
   company, location, and the full description body.
2. Read every resume in the configured folder, extract its readable text
   (``.pdf``, ``.docx``, ``.txt``, ``.md``), score each one against the job
   description with :mod:`src.tools.matching`, and select the highest scorer.

Ties are broken by the most recently modified file. Resume files are never
modified. Reading the description is a deterministic CDP ``page.evaluate`` (no
LLM), and the scoring is deterministic keyword/weight matching.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

from src.state import JobDescription, ResumeCandidate, Task3Outcome
from src.tools.browser import _loads, _safe
from src.tools.matching import score_resume

# Accepted resume file formats (case-insensitive).
RESUME_SUFFIXES = (".pdf", ".docx", ".txt", ".md")

_DOCX_TEXT_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"

# The open job's details (Task 3): title, company, location, and description body.
_JOB_DESCRIPTION_QUERY = """
() => {
  const pick = (selectors) => {
    for (const selector of selectors) {
      const el = document.querySelector(selector);
      if (el && (el.innerText || '').trim()) return el.innerText.trim();
    }
    return '';
  };
  return JSON.stringify({
    title: pick([
      '.job-details-jobs-unified-top-card__job-title',
      '.jobs-unified-top-card__job-title',
      'h1.t-24', 'h1'
    ]),
    company: pick([
      '.job-details-jobs-unified-top-card__company-name',
      '.jobs-unified-top-card__company-name',
      'a.topcard__org-name-link'
    ]),
    location: pick([
      '.job-details-jobs-unified-top-card__bullet',
      '.jobs-unified-top-card__bullet',
      '.topcard__flavor--bullet'
    ]),
    body: pick([
      '.jobs-description__content',
      '.jobs-box__html-content',
      '#job-details',
      '.jobs-description'
    ]),
    url: location.href
  });
}
"""


async def read_job_description(page) -> JobDescription:
    """Read the open job's title, company, location, and description (Task 3)."""
    payload = _loads(await _safe(page.evaluate(_JOB_DESCRIPTION_QUERY), ""))
    return JobDescription(
        title=(payload.get("title") or "").strip(),
        company=(payload.get("company") or "").strip(),
        location=(payload.get("location") or "").strip(),
        body=(payload.get("body") or "").strip(),
        page_url=payload.get("url") or None,
    )


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


def select_best_resume(
    job_description: JobDescription,
    resumes_dir: str | Path,
) -> Task3Outcome:
    """Score every resume in ``resumes_dir`` and select the best match."""
    files = list_resume_files(resumes_dir)
    outcome = Task3Outcome(
        job_description=job_description,
        resumes_dir=str(resumes_dir),
        resumes_found=len(files),
    )

    if not files:
        outcome.notes = "no resumes available in the folder"
        return outcome

    for path in files:
        error = ""
        try:
            text = extract_resume_text(path)
        except Exception as exc:  # noqa: BLE001 - a bad file must not stop the run
            text = ""
            error = f"{type(exc).__name__}: {exc}"

        result = score_resume(job_description.title, job_description.full_text, text)
        outcome.candidates.append(
            ResumeCandidate(
                path=str(path),
                score=result.score,
                matched_keywords=list(result.matched_skills),
                rationale=result.rationale,
                extracted=bool(text.strip()) and not error,
                error=error,
            )
        )

    # Prefer resumes whose text was read; only fall back to unreadable files when
    # nothing could be extracted at all.
    pool = [candidate for candidate in outcome.candidates if candidate.extracted] or list(
        outcome.candidates
    )
    best_score = max(candidate.score for candidate in pool)
    top = [candidate for candidate in pool if candidate.score == best_score]
    if len(top) > 1:
        # Tie-break: prefer the most recently modified file and record the tie.
        top.sort(key=lambda candidate: _safe_mtime(candidate.path), reverse=True)
        outcome.tie_break = (
            f"tie at score {best_score} across {len(top)} resumes; "
            "chose the most recently modified file"
        )

    best = top[0]
    outcome.selected_path = best.path
    outcome.selected_score = best.score
    outcome.rationale = best.rationale

    unreadable = [candidate.path for candidate in outcome.candidates if candidate.error]
    notes = [outcome.tie_break] if outcome.tie_break else []
    if unreadable:
        notes.append(f"could not read {len(unreadable)} resume(s): {', '.join(unreadable)}")
    outcome.notes = "; ".join(part for part in notes if part)
    return outcome


def _safe_mtime(path: str) -> float:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0
