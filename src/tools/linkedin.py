"""`session` (LinkedIn page operations) — search and modal interaction primitives.

Implemented in Task 3 (login detection), Task 5 (read a job, detect Easy Apply),
Task 12 (search results) and Task 13 (Easy Apply modal steps). Selectors used for
*reading* live here; fill selectors live in ``src/nodes/fill.py``.

Parsing is a pure function over HTML so it is unit-testable against saved fixtures
with no browser (SPEC.md §6). Every browser/network call routes through
``src/tools/guard.py`` (SPEC.md §8).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING

from playwright.sync_api import Page

if TYPE_CHECKING:  # avoid importing the guard at module load; only used as a type
    from src.tools.guard import Guard

LOGIN_URL = "https://www.linkedin.com/login"
FEED_URL = "https://www.linkedin.com/feed/"
MYNETWORK_URL = "https://www.linkedin.com/mynetwork/"

# URL fragments that identify an authenticated session vs. a login wall.
LOGGED_IN_URL_MARKERS = ("/feed", "/mynetwork")
LOGGED_OUT_URL_MARKERS = ("/login", "/authwall", "/checkpoint", "/uas/")


# ---------------------------------------------------------------------------
# Read selectors (class names on LinkedIn job pages).
#
# Several candidates are accepted so the reader survives LinkedIn's frequent
# class renames. Kept as module-level constants — never inline (SPEC.md §5).
# ---------------------------------------------------------------------------

TITLE_CLASSES = frozenset(
    {
        "job-details-jobs-unified-top-card__job-title",
        "jobs-unified-top-card__job-title",
        "topcard__title",
    }
)
COMPANY_CLASSES = frozenset(
    {
        "job-details-jobs-unified-top-card__company-name",
        "jobs-unified-top-card__company-name",
        "topcard__org-name-link",
    }
)
DESCRIPTION_CLASSES = frozenset(
    {
        "jobs-description__content",
        "jobs-description-content__text",
        "jobs-box__html-content",
    }
)
APPLY_BUTTON_CLASSES = frozenset(
    {
        "jobs-apply-button",
        "jobs-s-apply__button",
    }
)

_BUTTON_TAGS = frozenset({"button", "a"})
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_EASY_APPLY_TEXT = "easy apply"


@dataclass(frozen=True)
class JobDetails:
    """One job page's readable contents, plus Easy Apply availability."""

    job_id: str
    title: str
    company: str
    description: str
    url: str
    easy_apply: bool


def job_id_from_url(url: str) -> str:
    """Extract the LinkedIn numeric job id from a job/view or search URL.

    Raises ``ValueError`` for a URL that carries no job id, so a bad URL fails
    loudly instead of deduping everything under an empty key.
    """
    for pattern in (r"/jobs/view/(\d+)", r"[?&]currentJobId=(\d+)"):
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"cannot determine LinkedIn job id from URL: {url!r}")


def login_state_from_url(url: str) -> bool:
    """Pure predicate: does this LinkedIn URL indicate an authenticated session?

    Kept free of Playwright so it is unit-testable without a browser (SPEC.md §6).
    """
    lowered = url.lower()
    if any(marker in lowered for marker in LOGGED_OUT_URL_MARKERS):
        return False
    return any(marker in lowered for marker in LOGGED_IN_URL_MARKERS)


def is_logged_in(page: Page) -> bool:
    """Best-effort check that the current page reflects a live session."""
    return login_state_from_url(page.url)


def wait_for_login(page: Page, timeout_seconds: int, *, poll_seconds: float = 1.0) -> bool:
    """Block until the page shows an authenticated session or the timeout elapses."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if is_logged_in(page):
            return True
        time.sleep(poll_seconds)
    return is_logged_in(page)


# ---------------------------------------------------------------------------
# Pure HTML parsing (no browser) — the fixture-testable half of discovery.
# ---------------------------------------------------------------------------


def _class_set(attrs: list[tuple[str, str | None]]) -> set[str]:
    classes: set[str] = set()
    for name, value in attrs:
        if name == "class" and value:
            classes.update(value.split())
    return classes


def _clean(parts: list[str]) -> str:
    return " ".join(" ".join(parts).split())


class _JobCardParser(HTMLParser):
    """Collect title/company/description text and apply-button text from one page.

    Inherited frames propagate, so text inside nested markup (e.g. a company
    ``<a>`` or a title ``<span>``) is still attributed to its matched ancestor.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # (tag, in_title, in_company, in_description, in_apply) per open element.
        self._stack: list[tuple[str, bool, bool, bool, bool]] = []
        self._title: list[str] = []
        self._company: list[str] = []
        self._description: list[str] = []
        self._apply: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = _class_set(attrs)
        parent = self._stack[-1] if self._stack else ("", False, False, False, False)
        in_title = parent[1] or bool(classes & TITLE_CLASSES)
        in_company = parent[2] or bool(classes & COMPANY_CLASSES)
        in_description = parent[3] or bool(classes & DESCRIPTION_CLASSES)
        in_apply = parent[4] or tag in _BUTTON_TAGS or bool(classes & APPLY_BUTTON_CLASSES)
        if tag not in _VOID_TAGS:
            self._stack.append((tag, in_title, in_company, in_description, in_apply))
        if in_apply:
            for name, value in attrs:
                if name in ("aria-label", "title") and value:
                    self._apply.append(value)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if not self._stack:
            return
        _, in_title, in_company, in_description, in_apply = self._stack[-1]
        if in_title:
            self._title.append(data)
        if in_company:
            self._company.append(data)
        if in_description:
            self._description.append(data)
        if in_apply:
            self._apply.append(data)

    def result(self) -> tuple[str, str, str, bool]:
        easy_apply = any(_EASY_APPLY_TEXT in _clean([part]).lower() for part in self._apply)
        return (
            _clean(self._title),
            _clean(self._company),
            _clean(self._description),
            easy_apply,
        )


def _parse(html: str) -> tuple[str, str, str, bool]:
    parser = _JobCardParser()
    parser.feed(html)
    parser.close()
    return parser.result()


def detect_easy_apply(html: str) -> bool:
    """Pure predicate: does this job page offer LinkedIn Easy Apply?"""
    return _parse(html)[3]


def parse_job_page(html: str, *, url: str = "") -> JobDetails:
    """Extract a job's readable fields from its HTML. Pure: no browser, no network.

    ``job_id`` is derived from ``url`` when it carries one; otherwise it is empty
    so an unknown URL still parses (callers that require an id get a clear error
    from :func:`job_id_from_url`).
    """
    title, company, description, easy_apply = _parse(html)
    return JobDetails(
        job_id=job_id_from_url(url) if url else "",
        title=title,
        company=company,
        description=description,
        url=url,
        easy_apply=easy_apply,
    )


def read_job(page: Page, url: str, *, guard: Guard | None = None) -> JobDetails:
    """Navigate to a job URL and parse it. Browser I/O lives here, not in nodes.

    When a ``guard`` is supplied the fetched HTML is screened for a
    rate-limit/checkpoint page before anything is read (SPEC.md §8).
    """
    page.goto(url, wait_until="domcontentloaded")
    html = page.content()
    if guard is not None:
        guard.check_page_text(html)
    return parse_job_page(html, url=page.url or url)
