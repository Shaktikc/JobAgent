"""Task 2 regression: open a job whose Easy Apply button *is* present (BUG-036).

Clicking a results card can leave the details pane on the **previous** job (a
stale/missed card click). An already-applied job's pane has no Easy Apply control
at all, so the walk reported "no Easy Apply for this job" and skipped a job that
does offer it — reproduced live on LinkedIn (the pane showed Adactin's *applied*
Django job while the clicked card was a different one).

These tests are offline: they drive :func:`_scan_page` / :func:`open_job_card` with
a fake results page whose details pane can stay stale, which is exactly the live
failure. The real page is verified in a browser (see ``known Bugs/task_2_bugs.md``).
"""

from __future__ import annotations

import json

from src.configuration import SessionSettings, Settings
from src.tools import linkedin_job_selection as jobsel
from src.tools.linkedin_job_apply_button import pane_shows_job

_PANE_JS = "document.title"
_MODAL_JS = "jobs-easy-apply-modal"
_AI_JS = "data-autojob-ai"


class _FakeElement:
    """A fake card/button control (label via ``aria-label`` or ``innerText``)."""

    def __init__(self, label: str, *, aria: bool = False, tag: str = "DIV") -> None:
        self.label = label
        self.aria = label if aria else None
        self.tag = tag
        self.clicks = 0

    async def get_attribute(self, name: str) -> str | None:
        if name == "aria-label":
            return self.aria
        return None

    async def evaluate(self, js: str, *args) -> str:
        if "tagName" in js:
            return self.tag
        if "innerText" in js:
            return self.label
        return self.label

    async def click(self) -> None:
        self.clicks += 1
        if self.on_click is not None:
            self.on_click()

    on_click = None


class _FakePage:
    """Results page whose details pane title can lag behind the clicked card."""

    def __init__(self, cards: list[_FakeElement], pane_title: str, easy_jobs: set[str]) -> None:
        self.cards = cards
        self.pane_title = pane_title
        self.easy_jobs = easy_jobs  # pane titles whose job offers Easy Apply
        self.button_clicks = 0
        self.modal_open = False
        self.apply_button = _FakeElement("Easy Apply to this job", aria=True, tag="BUTTON")
        self.apply_button.on_click = self._open_modal

    def _open_modal(self) -> None:
        self.modal_open = True

    async def evaluate(self, js: str, *args):
        if _PANE_JS in js:
            return json.dumps({"title": self.pane_title})
        if _MODAL_JS in js:
            text = "Easy Apply" if self.modal_open else ""
            return json.dumps({"open": self.modal_open, "text": text})
        if _AI_JS in js:
            return json.dumps({"count": 0})
        return ""

    async def get_elements_by_css_selector(self, selector: str) -> list:
        if selector == "button.jobs-apply-button":
            return [self.apply_button] if self.pane_title in self.easy_jobs else []
        if selector == "li.jobs-search-results__list-item":
            return list(self.cards)
        return []

    async def get_url(self) -> str:
        return "https://www.linkedin.com/jobs/search-results/"

    async def get_title(self) -> str:
        return "Jobs"


def _settings(tmp_path) -> Settings:
    return Settings(
        session=SessionSettings(
            headless=True,
            post_click_wait_seconds=0.0,
            # Keep the two waits short: these tests never want the walk to sit on
            # a deadline, and the retry/verify logic is what they exercise.
            easy_apply_timeout_seconds=0.05,
            pane_switch_timeout_seconds=0.05,
        ),
        data_dir=tmp_path / "data",
    )


def _card(title: str, *, on_click=None) -> _FakeElement:
    element = _FakeElement(f"{title} Acme Sydney, NSW (On-site) Easy Apply")
    element.on_click = on_click
    return element


# --- Matching the pane's job against the clicked card ------------------------
def test_pane_shows_job_accepts_badges_and_card_metadata() -> None:
    assert pane_shows_job("Django Developer", "Django Developer (Verified job)") is True
    assert pane_shows_job(
        "Django Developer", "Django Developer Adactin Sydney, NSW (On-site) Applied · Easy Apply"
    ) is True
    # A different job is a mismatch (this is the stale pane).
    assert pane_shows_job("Senior Backend Engineer - AI Platform", "Django Developer") is False
    # Unreadable titles never block: the check only ever adds a retry.
    assert pane_shows_job("", "Django Developer") is True
    assert pane_shows_job("Django Developer", "") is True


# --- Choosing the apply button ----------------------------------------------
async def test_apply_button_prefers_easy_apply_over_a_stale_apply_button() -> None:
    """An external "Apply" first must not mask the real Easy Apply button."""
    page = _FakePage([], pane_title="Django Developer", easy_jobs={"Django Developer"})
    external = _FakeElement("Apply on company website", tag="BUTTON")
    easy = _FakeElement("Easy Apply to this job", tag="BUTTON")

    async def _select(selector: str) -> list:
        return [external, easy] if selector == "button.jobs-apply-button" else []

    page.get_elements_by_css_selector = _select  # type: ignore[method-assign]

    button, label = await jobsel.find_job_apply_button(page)

    assert button is easy
    assert label == "Easy Apply to this job"


async def test_apply_button_returns_the_first_match_when_none_is_easy_apply() -> None:
    """An external-apply pane still returns its button, so the caller can skip
    the job straight away instead of waiting out the timeout."""
    page = _FakePage([], pane_title="Django Developer", easy_jobs=set())
    external = _FakeElement("Apply on company website", tag="BUTTON")

    async def _select(selector: str) -> list:
        return [external] if selector == "button.jobs-apply-button" else []

    page.get_elements_by_css_selector = _select  # type: ignore[method-assign]

    button, label = await jobsel.find_job_apply_button(page)

    assert button is external
    assert label == "Apply on company website"


async def test_apply_button_falls_back_to_an_easy_apply_link() -> None:
    page = _FakePage([], pane_title="Django Developer", easy_jobs=set())
    link = _FakeElement("Easy Apply", tag="A")

    async def _select(selector: str) -> list:
        return [link] if selector == "a" else []

    page.get_elements_by_css_selector = _select  # type: ignore[method-assign]

    assert await jobsel.find_job_apply_button(page) == (link, "Easy Apply")


# --- The walk: a stale pane must not look like "no Easy Apply" ---------------
async def test_walk_retries_a_click_that_leaves_the_pane_stale(tmp_path) -> None:
    card = _card("Django Developer")  # clicking never moves the pane
    page = _FakePage([card], pane_title="Senior Backend Engineer", easy_jobs={"Django Developer"})

    outcome = await jobsel._task2_on_page(page, _settings(tmp_path), lambda _m: None)

    assert page.pane_title == "Senior Backend Engineer"  # the click never took
    assert card.clicks == 2  # tried twice: the fresh handle is the fix
    assert outcome.easy_apply_clicked is False
    assert outcome.application_form_opened is False
    assert "no Easy Apply" not in outcome.notes
    assert "still shows Senior Backend Engineer" in outcome.notes


async def test_walk_opens_the_job_when_the_retry_switches_the_pane(tmp_path) -> None:
    """The first click is swallowed; the retry (a fresh handle) opens the job."""
    page_holder: dict[str, _FakePage] = {}

    def _click() -> None:
        if card.clicks >= 2:  # only the retry actually opens the job
            page_holder["page"].pane_title = "Django Developer"

    card = _card("Django Developer", on_click=_click)
    page = _FakePage([card], pane_title="Senior Backend Engineer", easy_jobs={"Django Developer"})
    page_holder["page"] = page

    outcome = await jobsel._task2_on_page(page, _settings(tmp_path), lambda _m: None)

    assert card.clicks == 2
    assert outcome.easy_apply_button_found is True
    assert outcome.easy_apply_clicked is True
    assert outcome.application_form_opened is True
    assert outcome.job_title.startswith("Django Developer")


async def test_walk_skips_a_job_whose_pane_really_has_no_easy_apply(tmp_path) -> None:
    """A pane that *does* show the job but has no Easy Apply is a genuine skip."""
    card = _card("Django Developer")

    def _click() -> None:
        page.pane_title = "Django Developer"

    card.on_click = _click
    page = _FakePage([card], pane_title="Senior Backend Engineer", easy_jobs=set())

    outcome = await jobsel._task2_on_page(page, _settings(tmp_path), lambda _m: None)

    assert card.clicks == 1  # the pane matched, so no retry
    assert outcome.skipped_jobs == 1
    assert outcome.easy_apply_button_found is False
    assert outcome.easy_apply_clicked is False
    assert "still shows" not in outcome.notes


async def test_open_job_card_reports_the_pane_it_actually_saw(tmp_path) -> None:
    card = _card("Django Developer")
    page = _FakePage([card], pane_title="Opus RS AI Engineer", easy_jobs=set())

    opened, pane_title = await jobsel.open_job_card(
        page, card, "Django Developer", _settings(tmp_path), lambda _m: None
    )

    assert opened is False
    assert pane_title == "Opus RS AI Engineer"
    assert card.clicks == 2
