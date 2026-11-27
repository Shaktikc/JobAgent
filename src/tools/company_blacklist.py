"""Task 32: skip LinkedIn postings from companies the user blacklisted.

The user lists companies in ``blacklist company/companies.json`` at the project
root: a JSON array of company names, as LinkedIn displays them (for example
``["Acme", "Globex Corp"]``). Blank names are ignored. A company matches only on
its **entire** name, ignoring case and leading, trailing, or repeated
whitespace: ``Acme`` matches `` ACME `` but not ``Acme Labs`` (list each variant
as its own entry to skip it too).

The list is loaded once per process (one run) by :func:`get_blacklist`. A missing
or empty file (or ``[]``) leaves job selection unchanged. A file that exists but
cannot be read, or is not a JSON list of names, raises
:class:`BlacklistFileError`, which the CLI reports before any job is processed.

This module is pure (no browser); the results scanner
(:mod:`src.tools.linkedin_company_skip`) owns the browser-side checks.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

from src.configuration import PROJECT_ROOT

BLACKLIST_FILE = PROJECT_ROOT / "blacklist company" / "companies.json"


class BlacklistFileError(RuntimeError):
    """The blacklist file exists but could not be read."""


def normalize_company(name: str | None) -> str:
    """Lowercase ``name`` and collapse/trim its whitespace (``""`` when blank)."""
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def parse_blacklist(names: Iterable[str]) -> frozenset[str]:
    """The normalized company names in ``names`` (blank entries ignored)."""
    if isinstance(names, str):
        names = [names]
    normalized = (normalize_company(name) for name in names or ())
    return frozenset(name for name in normalized if name)


def load_blacklist(path: Path | None = None) -> frozenset[str]:
    """Read the JSON blacklist at ``path``; a missing or empty file is an empty list.

    The file holds a JSON array of company-name strings. Unreadable files,
    invalid JSON, or any other shape raise :class:`BlacklistFileError`.
    """
    path = path or BLACKLIST_FILE
    if not path.exists():
        return frozenset()
    try:
        text = path.read_text(encoding="utf-8-sig")
        data = json.loads(text) if text.strip() else []
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BlacklistFileError(
            f"could not read the company blacklist {path}: {exc}"
        ) from exc
    if not isinstance(data, list) or not all(isinstance(name, str) for name in data):
        raise BlacklistFileError(
            f"could not read the company blacklist {path}: expected a JSON list of "
            'company names, for example ["Acme", "Globex Corp"]'
        )
    return parse_blacklist(data)


_CACHE: dict[str, frozenset[str]] = {}


def get_blacklist() -> frozenset[str]:
    """The run's blacklist, read from :data:`BLACKLIST_FILE` on first use only."""
    if "names" not in _CACHE:
        _CACHE["names"] = load_blacklist()
    return _CACHE["names"]


def reset_blacklist_cache() -> None:
    """Forget the cached list (tests, or a new run in the same process)."""
    _CACHE.clear()


def is_blacklisted(company: str | None, blacklist: frozenset[str]) -> bool:
    """True when ``company``'s entire normalized name is in ``blacklist``."""
    name = normalize_company(company)
    return bool(name) and name in blacklist


def blacklisted_line(text: str | None, blacklist: frozenset[str]) -> str:
    """The first whole line of ``text`` that names a blacklisted company, or ``""``.

    A job card's text puts the company on its own line, so each line is compared
    as a whole name; a title such as "Engineer at Acme" never matches ``acme``.
    """
    if not blacklist:
        return ""
    for line in (text or "").splitlines():
        if is_blacklisted(line, blacklist):
            return line.strip()
    return ""


# A pagination failure that leaves the current page unscanned (see
# src.tools.linkedin_results_scan): the scan did not genuinely run out of jobs.
_UNFINISHED_SCAN_MARKERS = ("did not change", "disappeared")

NO_ELIGIBLE_JOB_REASON = (
    "no eligible job remained; every remaining posting was skipped "
    "(including blacklisted companies)"
)


def only_blacklisted_jobs_left(task2) -> bool:
    """True when a Task 2 scan selected nothing because blacklisted jobs were skipped.

    That is a clean end of the run (nothing eligible remains), not a browser
    failure to repair. A scan cut short by a pagination failure is not clean.
    """
    if task2 is None or not getattr(task2, "blacklisted_jobs_skipped", 0):
        return False
    if task2.job_selected or task2.easy_apply_clicked:
        return False
    notes = (task2.notes or "").lower()
    return not any(marker in notes for marker in _UNFINISHED_SCAN_MARKERS)


__all__ = [
    "BLACKLIST_FILE",
    "NO_ELIGIBLE_JOB_REASON",
    "BlacklistFileError",
    "blacklisted_line",
    "get_blacklist",
    "is_blacklisted",
    "load_blacklist",
    "normalize_company",
    "only_blacklisted_jobs_left",
    "parse_blacklist",
    "reset_blacklist_cache",
]
