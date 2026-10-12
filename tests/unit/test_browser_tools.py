"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from src.configuration import SessionSettings, Settings
from src.state import DEFAULT_LOGIN_URL, Task5Outcome
from src.tools import browser as browser_tools
from src.tools import linkedin_easy_apply_fill as fill_tools
from src.tools import linkedin_search as linkedin_tools
from src.tools.answers import normalize_question
from src.tools.linkedin import build_jobs_search_url
from src.tools.llm_answers import QuestionDecision

SEARCH_URL = build_jobs_search_url("software engineer")


class FakeElement:
    def __init__(
        self,
        label: str,
        *,
        aria_label: bool = True,
        css_class: str = "",
        aria_pressed: str | None = None,
        aria_checked: str | None = None,
        data_live_test: bool = False,
        on_click=None,
        click_error: Exception | None = None,
    ) -> None:
        self.label = label
        self.aria_label = aria_label
        self.css_class = css_class
        self.aria_pressed = aria_pressed
        self.aria_checked = aria_checked
        self.data_live_test = data_live_test
        self.on_click = on_click
        self.click_error = click_error
        self.clicked = False
        self.scrolled = False
        self.filled: str | None = None
        self.selected_option = None
        self.checked = False

    async def get_attribute(self, name: str) -> str | None:
        if name == "aria-label" and self.aria_label:
            return self.label
        if name == "class":
            return self.css_class or None
        if name == "aria-pressed":
            return self.aria_pressed
        if name == "aria-checked":
            return self.aria_checked
        if name == "data-live-test-job-apply-button":
            return "" if self.data_live_test else None
        return None

    async def evaluate(self, js: str, *args) -> str:
        if "scrollIntoView" in js:
            self.scrolled = True
            return self.label
        if "HTMLSelectElement" in js:
            self.selected_option = args[0] if args else None
            return str(self.selected_option)
        if "setter.call(this, value)" in js:
            self.filled = args[0] if args else None
            return str(self.filled)
        return self.label

    async def fill(self, value: str, clear: bool = True) -> None:
        self.filled = value

    async def select_option(self, values) -> None:
        self.selected_option = values

    async def check(self) -> None:
        self.checked = True

    async def click(self) -> None:
        self.clicked = True
        if self.on_click is not None:
            self.on_click()
        if self.click_error is not None:
            raise self.click_error


class FakePage:
    def __init__(
        self,
        *,
        by_selector: dict[str, list] | None = None,
        login_payload=None,
        results_count: int = 0,
        filter_selected: bool = False,
        ready: str = "complete",
        details_apply_labels: dict[int, str] | None = None,
        modal_text: str = "Apply to Backend Engineer",
        apply_opens_modal: bool = True,
        job_description: dict | None = None,
        form_enumerations: list[dict] | None = None,
        form_buttons_queue: list[list[dict]] | None = None,
        resume_options: dict | None = None,
        form_open_default: bool = False,
        ai_buttons: list | None = None,
        ai_buttons_queue: list | None = None,
        ai_job_cards: list | None = None,
    ) -> None:
        self.by_selector = by_selector or {}
        self.login_payload = login_payload or {"path": "/feed/", "nav": True, "loginForm": False}
        self.results_count = results_count
        self.ai_job_cards = list(ai_job_cards or [])
        self.filter_selected = filter_selected
        self.ready = ready
        self.goto_calls: list[str] = []
        self.pressed: list[str] = []
        self.current_url = DEFAULT_LOGIN_URL
        # Task 2: the details pane shows the apply button for the selected job.
        self.details_apply_labels = details_apply_labels or {}
        self.selected_job: int | None = None
        self.modal_open = False
        self.modal_text = modal_text
        self.apply_opens_modal = apply_opens_modal
        # Task 3: the details pane also exposes the job description.
        self.job_description = job_description or {
            "title": "Backend Engineer",
            "company": "Acme",
            "location": "Remote",
            "body": "We build services with Python and AWS. 5+ years required.",
            "url": "https://www.linkedin.com/jobs/view/1",
        }
        # Task 4: form enumeration / resume / button fakes.
        self.form_enumerations = list(form_enumerations or [])
        self.form_buttons_queue = list(form_buttons_queue or [])
        self.resume_options = resume_options or {"options": [], "fileInput": False}
        self.form_open_default = form_open_default
        # Task 1 enhancement: controls the runtime AI-job-search scan returns.
        self.ai_buttons = list(ai_buttons or [])
        # Each evaluate pops the next batch; the last batch persists.
        self.ai_buttons_queue = list(ai_buttons_queue or [])
        self.ai_elements: dict[str, FakeElement] = {}
        self.fill_elements: dict[str, FakeElement] = {}
        self.button_elements: dict[str, FakeElement] = {}
        self.resume_elements: dict[str, FakeElement] = {}
        self.select_elements: dict[str, FakeElement] = {}
        self.upload_elements: dict[str, FakeElement] = {}
        self.file_element: FakeElement | None = None

    async def goto(self, url: str) -> None:
        self.goto_calls.append(url)
        self.current_url = url
        if "f_AL=true" in url:
            self.filter_selected = True

    async def press(self, key: str) -> None:
        self.pressed.append(key)

    async def get_url(self) -> str:
        return self.current_url

    async def get_title(self) -> str:
        return "LinkedIn"

    async def evaluate(self, js: str, *args):
        if "data-autojob-ai" in js:
            if self.ai_buttons_queue:
                buttons = (
                    self.ai_buttons_queue.pop(0)
                    if len(self.ai_buttons_queue) > 1
                    else self.ai_buttons_queue[0]
                )
            else:
                buttons = self.ai_buttons
            self.ai_elements = {}
            candidates = []
            for i, element in enumerate(buttons):
                marker = f"ai{i}"
                self.ai_elements[marker] = element
                candidates.append({"marker": marker, "label": element.label})
            return json.dumps({"candidates": candidates})
        if "data-autojob-fill" in js:
            if self.form_enumerations:
                return json.dumps(self.form_enumerations.pop(0))
            return json.dumps({"open": self.form_open_default, "fields": []})
        if "data-autojob-resume" in js:
            if isinstance(self.resume_options, list):
                queued = self.resume_options.pop(0) if self.resume_options else {}
                return json.dumps(queued)
            return json.dumps(self.resume_options)
        if "data-autojob-btn" in js:
            if self.form_buttons_queue:
                return json.dumps({"buttons": self.form_buttons_queue.pop(0)})
            return json.dumps({"buttons": []})
        if "readyState" in js:
            return self.ready
        if "location.pathname" in js:
            payload = self.login_payload() if callable(self.login_payload) else self.login_payload
            return json.dumps(payload)
        if "jobs-search-results" in js:
            return json.dumps({"count": self.results_count})
        if "data-autojob-card" in js:
            return json.dumps({"count": len(self.ai_job_cards)})
        if "jobs-easy-apply-modal" in js:
            text = self.modal_text if self.modal_open else ""
            return json.dumps({"open": self.modal_open, "text": text})
        if "job-details-jobs-unified-top-card" in js:
            return json.dumps(self.job_description)
        if "aria-pressed" in js:
            return json.dumps({"selected": self.filter_selected})
        return ""

    async def get_elements_by_css_selector(self, selector: str) -> list:
        if selector == "button.jobs-apply-button":
            return [self._apply_button()] if self.selected_job is not None else []
        for attribute, registry in (
            ("data-autojob-fill", self.fill_elements),
            ("data-autojob-btn", self.button_elements),
            ("data-autojob-resume", self.resume_elements),
            ("data-autojob-resume-select", self.select_elements),
            ("data-autojob-resume-upload", self.upload_elements),
            ("data-autojob-ai", self.ai_elements),
        ):
            match = re.fullmatch(rf'\[{attribute}="([^"]+)"\]', selector)
            if match:
                element = registry.get(match.group(1))
                return [element] if element is not None else []
        if selector in {'[data-autojob-file="1"]', 'input[type="file"]'}:
            return [self.file_element] if self.file_element is not None else []
        if selector == "[data-autojob-card]":
            return list(self.ai_job_cards)
        return list(self.by_selector.get(selector, []))

    def _apply_button(self) -> FakeElement:
        label = self.details_apply_labels.get(self.selected_job, "Apply")

        def _open_modal() -> None:
            if self.apply_opens_modal:
                self.modal_open = True

        return FakeElement(label, on_click=_open_modal)


class FakeSession:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.started = False
        self.killed = False
        self.screenshot_path: str | None = None

    async def start(self) -> None:
        self.started = True

    async def kill(self) -> None:
        self.killed = True

    async def new_page(self) -> FakePage:
        return self.page

    async def take_screenshot(self, path: str | None = None, full_page: bool = False) -> None:
        Path(path).write_bytes(b"png")
        self.screenshot_path = path


def _filter_element(page: FakePage) -> FakeElement:
    """An Easy Apply filter control that flips the page's filter state when clicked."""

    def _click() -> None:
        page.filter_selected = True

    return FakeElement("Easy Apply filter.", on_click=_click)


# Real class strings captured from the live LinkedIn results page (see
# test_find_easy_apply_filter_from_real_linkedin_dom).
_FILTER_PILL_CLASS = (
    "artdeco-pill artdeco-pill--slate artdeco-pill--2 artdeco-pill--choice ember-view "
    "search-reusables__filter-pill-button"
)
_APPLY_BUTTON_CLASS = (
    "jobs-apply-button artdeco-button artdeco-button--3 artdeco-button--primary ember-view"
)


def _job_card(page: FakePage, index: int, title: str) -> FakeElement:
    """A job card that selects its details pane when clicked."""

    def _select() -> None:
        page.selected_job = index

    return FakeElement(title, on_click=_select)


def _settings(tmp_path, **session) -> Settings:
    # Task 5's browser prompt is off by default in tests; Task 5 tests enable it.
    session.setdefault("ask_human", False)
    # Task 1's optional AI-button wait is skipped by default so tests stay fast.
    session.setdefault("ai_search_timeout_seconds", 0)
    return Settings(session=SessionSettings(**session), data_dir=tmp_path)


async def test_is_logged_in_uses_path() -> None:
    logged_in = FakePage(login_payload={"path": "/feed/", "nav": False, "loginForm": False})
    assert await browser_tools.is_logged_in(logged_in) is True

    on_login = FakePage(login_payload={"path": "/login", "nav": False, "loginForm": True})
    assert await browser_tools.is_logged_in(on_login) is False


async def test_is_logged_in_falls_back_to_nav_on_ambiguous_path() -> None:
    nav = FakePage(login_payload={"path": "/", "nav": True, "loginForm": False})
    assert await browser_tools.is_logged_in(nav) is True

    no_nav = FakePage(login_payload={"path": "/", "nav": False, "loginForm": False})
    assert await browser_tools.is_logged_in(no_nav) is False


async def test_wait_for_login_succeeds_after_user_logs_in() -> None:
    states = ["/login", "/login", "/feed/"]

    def payload():
        return {"path": states.pop(0) if states else "/feed/", "nav": False, "loginForm": False}

    page = FakePage(login_payload=payload)
    assert await browser_tools.wait_for_login(page, timeout_seconds=2, poll_seconds=0.01) is True


async def test_wait_for_login_times_out() -> None:
    page = FakePage(login_payload={"path": "/login", "nav": False, "loginForm": True})
    assert (
        await browser_tools.wait_for_login(page, timeout_seconds=0.05, poll_seconds=0.01) is False
    )


async def test_results_count() -> None:
    assert await browser_tools.results_count(FakePage(results_count=0)) == 0
    assert await browser_tools.results_count(FakePage(results_count=12)) == 12


async def test_results_count_counts_ai_job_cards() -> None:
    """The AI/semantic results page has no classic <li> cards, so results_count
    falls back to counting the div[role="button"] job cards it marks."""
    card = FakeElement("Backend Engineer")
    page = FakePage(results_count=0, ai_job_cards=[card])
    assert await browser_tools.results_count(page) == 1


async def test_type_jobs_search_types_and_submits(tmp_path) -> None:
    field = FakeElement("Search by title, skill, or company")
    submit = FakeElement("Search")
    page = FakePage(
        by_selector={
            "input.jobs-search-box__keyboard-text-input": [field],
            "button.jobs-search-box__submit-button": [submit],
        }
    )
    typed = await browser_tools.type_jobs_search(page, "software engineer", _settings(tmp_path))

    assert typed is True
    assert field.filled == "software engineer"
    assert submit.clicked is True
    # The search bar is already on the page, so the Jobs tab is not reopened.
    assert page.goto_calls == []


async def test_type_jobs_search_opens_jobs_tab_only_when_search_bar_absent(tmp_path) -> None:
    page = FakePage()
    typed = await browser_tools.type_jobs_search(page, "software engineer", _settings(tmp_path))

    assert typed is False
    # Without a search bar the Jobs tab is opened once to get one.
    assert page.goto_calls == [browser_tools._JOBS_TAB_URL]


async def test_type_jobs_search_uses_enter_without_submit_button(tmp_path) -> None:
    field = FakeElement("Search by title, skill, or company")
    page = FakePage(by_selector={"input.jobs-search-box__keyboard-text-input": [field]})
    typed = await browser_tools.type_jobs_search(page, "software engineer", _settings(tmp_path))

    assert typed is True
    assert field.filled == "software engineer"
    assert page.pressed == ["Enter"]


async def test_type_jobs_search_types_into_ai_prompt_and_submits(tmp_path) -> None:
    # The AI job search page's prompt is not the standard jobs search bar; it must
    # still be recognised and typed into.
    ai_prompt = FakeElement("Describe the job you want")
    page = FakePage(by_selector={"input": [ai_prompt]})

    typed = await browser_tools.type_jobs_search(page, "software engineer", _settings(tmp_path))

    assert typed is True
    assert ai_prompt.filled == "software engineer"
    assert page.pressed == ["Enter"]
    assert page.goto_calls == []


async def test_find_jobs_search_input_matches_ai_prompt() -> None:
    ai_prompt = FakeElement("Describe the job you want")
    page = FakePage(by_selector={"input": [FakeElement("City"), ai_prompt]})
    assert await browser_tools.find_jobs_search_input(page) is ai_prompt


async def test_type_jobs_search_returns_false_without_search_bar(tmp_path) -> None:
    page = FakePage()
    assert await browser_tools.type_jobs_search(page, "x", _settings(tmp_path)) is False


async def test_find_jobs_search_input_by_label_fallback() -> None:
    labelled = FakeElement("Search by title, skill, or company")
    page = FakePage(by_selector={"input": [FakeElement("City"), labelled]})
    assert await browser_tools.find_jobs_search_input(page) is labelled


async def test_open_jobs_search_types_then_reports_results(tmp_path) -> None:
    field = FakeElement("Search by title, skill, or company")
    page = FakePage(
        by_selector={"input.jobs-search-box__keyboard-text-input": [field]},
        results_count=7,
    )
    found, count, _url = await browser_tools.open_jobs_search(
        page, "software engineer", _settings(tmp_path)
    )
    assert (found, count) == (True, 7)
    assert field.filled == "software engineer"
    # The typed path must not navigate straight to the search URL.
    assert SEARCH_URL not in page.goto_calls


async def test_open_jobs_search_falls_back_to_url_without_search_bar(tmp_path) -> None:
    page = FakePage(results_count=4)
    found, count, url = await browser_tools.open_jobs_search(
        page, "software engineer", _settings(tmp_path)
    )
    assert (found, count) == (True, 4)
    assert url == SEARCH_URL
    assert SEARCH_URL in page.goto_calls


async def test_open_jobs_search_detects_ai_job_cards_promptly(tmp_path) -> None:
    """On the AI/semantic results page the classic <li> cards are absent but the
    div[role="button"] job cards are present. results_count must find them so the
    run does not wait for cards the classic selectors cannot see."""
    field = FakeElement("Search by title, skill, or company")
    card = FakeElement("Backend Engineer")
    page = FakePage(
        by_selector={"input.jobs-search-box__keyboard-text-input": [field]},
        results_count=0,
        ai_job_cards=[card],
    )
    found, count, _url = await browser_tools.open_jobs_search(
        page, "software engineer", _settings(tmp_path)
    )
    assert (found, count) == (True, 1)
    assert field.filled == "software engineer"
    assert SEARCH_URL not in page.goto_calls


async def test_find_easy_apply_filter_prefers_filter_label() -> None:
    job_button = FakeElement("Easy Apply to Backend Engineer at Acme")
    filter_button = FakeElement("Easy Apply filter.")
    page = FakePage(by_selector={"button[aria-label*='Easy Apply']": [job_button, filter_button]})
    # Both match `*='Easy Apply'`; the filter must win over the job's button.
    assert await browser_tools.find_easy_apply_filter(page) is filter_button


async def test_find_easy_apply_filter_prefers_toggle_pill_over_apply_button() -> None:
    """The filter pill and the blue apply button share the label "Easy Apply".

    From the real page: the pill is role="radio" with aria-checked (id
    searchFilter_applyWithLinkedin, class search-reusables__filter-pill-button);
    the blue button is jobs-apply-button / artdeco-button--primary. Only the pill
    is a choice toggle, so it must win even though it appears after the apply
    button and its label is just "Easy Apply filter.".
    """
    apply_btn = FakeElement(
        "Easy Apply to Senior Software Engineer at Care GP",
        aria_label=False,
        css_class="jobs-apply-button artdeco-button artdeco-button--primary ember-view",
        data_live_test=True,
    )
    pill = FakeElement(
        "Easy Apply filter.",
        css_class=_FILTER_PILL_CLASS,
        aria_checked="false",
    )
    page = FakePage(
        by_selector={
            "button, [role='button']": [apply_btn, pill],
            "button[aria-label*='Easy Apply']": [apply_btn, pill],
        }
    )
    assert await browser_tools.find_easy_apply_filter(page) is pill


async def test_find_easy_apply_filter_from_real_linkedin_dom() -> None:
    """Regression test built from the real captured LinkedIn DOM.

    The filter pill (role="radio", aria-checked, id searchFilter_applyWithLinkedin)
    must be selected and the two blue jobs-apply-button controls skipped, even
    though all three mention "Easy Apply".
    """
    apply_top = FakeElement(
        "Easy Apply to Programmer (Unity) at True Anomaly Entertainment",
        css_class=_APPLY_BUTTON_CLASS,
        data_live_test=True,
    )
    apply_sticky = FakeElement(
        "Easy Apply to Programmer (Unity) at True Anomaly Entertainment",
        css_class=_APPLY_BUTTON_CLASS,
        data_live_test=True,
    )
    filter_pill = FakeElement(
        "Easy Apply filter.",
        css_class=_FILTER_PILL_CLASS,
        aria_checked="false",
    )
    page = FakePage(
        by_selector={
            "button, [role='button']": [apply_top, apply_sticky, filter_pill],
            "button[aria-label*='Easy Apply']": [apply_top, apply_sticky, filter_pill],
        }
    )
    assert await browser_tools.find_easy_apply_filter(page) is filter_pill


async def test_find_easy_apply_filter_never_returns_the_apply_button() -> None:
    """A lone blue apply button (no filter toggle) must not be returned as the filter."""
    apply_btn = FakeElement(
        "Easy Apply",
        aria_label=False,
        css_class="jobs-apply-button artdeco-button artdeco-button--primary",
        data_live_test=True,
    )
    page = FakePage(by_selector={"button, [role='button']": [apply_btn]})
    assert await browser_tools.find_easy_apply_filter(page) is None


async def test_find_easy_apply_filter_skips_apply_button_by_class() -> None:
    """The blue apply button is skipped by its jobs-apply-button class, so a
    bare-label Easy Apply filter pill (without a toggle attribute) still wins by
    its 'filter' name."""
    apply_btn = FakeElement(
        "Easy Apply",
        aria_label=False,
        css_class="jobs-apply-button artdeco-button artdeco-button--primary",
        data_live_test=True,
    )
    pill = FakeElement("Easy Apply filter.")
    page = FakePage(by_selector={"button, [role='button']": [apply_btn, pill]})
    assert await browser_tools.find_easy_apply_filter(page) is pill


async def test_read_job_cards() -> None:
    page = FakePage()
    cards = [_job_card(page, 0, "Backend Engineer"), _job_card(page, 1, "Data Engineer")]
    page.by_selector = {"li.jobs-search-results__list-item": cards}

    assert await browser_tools.read_job_cards(page) == cards
    assert await browser_tools.read_job_cards(FakePage()) == []


async def test_read_job_cards_finds_ai_job_cards() -> None:
    """On the AI/semantic results page the cards are div[role="button"], not
    classic <li> items; read_job_cards marks them and returns them."""
    card = FakeElement("Backend Engineer")
    page = FakePage(ai_job_cards=[card])
    assert await browser_tools.read_job_cards(page) == [card]


async def test_find_job_apply_button_reads_details_pane() -> None:
    page = FakePage(details_apply_labels={2: "Easy Apply to Data Engineer at Acme"})
    page.selected_job = 2

    button, label = await browser_tools.find_job_apply_button(page)
    assert button is not None
    assert label == "Easy Apply to Data Engineer at Acme"


async def test_find_job_apply_button_matches_semantic_layout_label() -> None:
    """The AI/semantic layout's apply button has hashed classes, so it is matched
    by its accessible label ("Easy Apply to this job") rather than a CSS class."""
    page = FakePage(
        by_selector={
            'button[aria-label^="Easy Apply to" i]': [FakeElement("Easy Apply to this job")]
        }
    )

    button, label = await browser_tools.find_job_apply_button(page)

    assert button is not None
    assert label == "Easy Apply to this job"


async def test_find_job_apply_button_none_without_selection() -> None:
    assert await browser_tools.find_job_apply_button(FakePage()) == (None, "")


async def test_find_job_apply_button_fallback_skips_job_cards() -> None:
    """A job card whose text contains "Easy Apply" must not be chosen as the
    apply button when the CSS selectors miss the details pane's button.

    On the AI/semantic results page the job cards are div[role="button"] and their
    accessible text carries the "Easy Apply" badge, so a naive fallback scan picks
    the first card and clicks it instead of the blue "Easy Apply" button (the Task
    2 bug). The fallback must exclude job cards and return the real apply button.
    """
    card = FakeElement(
        "Senior Software Engineer (Founding Team) Care GP Sydney, NSW (On-site) "
        "Actively reviewing applicants Easy Apply",
        aria_label=False,
    )
    apply_button = FakeElement("Easy Apply to Senior Software Engineer at Care GP")
    page = FakePage(by_selector={"button, [role='button']": [card, apply_button]})

    button, label = await browser_tools.find_job_apply_button(page)

    assert button is apply_button
    assert label == "Easy Apply to Senior Software Engineer at Care GP"
    # The job card was never picked as the apply button.
    assert button is not card


async def test_task2_selects_job_and_opens_form(tmp_path) -> None:
    page = FakePage(
        results_count=3,
        details_apply_labels={0: "Easy Apply to Backend Engineer at Acme"},
    )
    page.by_selector = {
        "li.jobs-search-results__list-item": [
            _job_card(page, 0, "Backend Engineer"),
            _job_card(page, 1, "Data Engineer"),
        ]
    }

    outcome = await browser_tools._task2_on_page(
        page, _settings(tmp_path, post_click_wait_seconds=0), lambda _m: None
    )

    assert outcome.jobs_seen == 2
    assert outcome.job_index == 0
    assert outcome.job_title == "Backend Engineer"
    assert outcome.skipped_jobs == 0
    assert outcome.easy_apply_button_found is True
    assert outcome.easy_apply_clicked is True
    assert outcome.application_form_opened is True


async def test_task2_skips_jobs_without_easy_apply(tmp_path) -> None:
    page = FakePage(
        details_apply_labels={0: "Apply on company website", 1: "Apply"},
    )
    page.by_selector = {
        "li.jobs-search-results__list-item": [
            _job_card(page, 0, "External A"),
            _job_card(page, 1, "External B"),
        ]
    }

    outcome = await browser_tools._task2_on_page(
        page, _settings(tmp_path, post_click_wait_seconds=0), lambda _m: None
    )

    assert outcome.skipped_jobs == 2
    assert outcome.easy_apply_button_found is False
    assert outcome.easy_apply_clicked is False
    assert outcome.application_form_opened is False


async def test_task2_reports_when_form_does_not_open(tmp_path) -> None:
    page = FakePage(
        details_apply_labels={0: "Easy Apply to Backend Engineer at Acme"},
        apply_opens_modal=False,
    )
    page.by_selector = {"li.jobs-search-results__list-item": [_job_card(page, 0, "Backend")]}

    outcome = await browser_tools._task2_on_page(
        page,
        _settings(tmp_path, post_click_wait_seconds=0, easy_apply_timeout_seconds=0.05),
        lambda _m: None,
    )

    assert outcome.easy_apply_clicked is True
    assert outcome.application_form_opened is False
    assert outcome.notes


async def test_task2_skips_applied_jobs_and_opens_first_unapplied(tmp_path) -> None:
    page = FakePage(
        details_apply_labels={1: "Easy Apply to Data Engineer at Acme"},
    )
    page.by_selector = {
        "li.jobs-search-results__list-item": [
            _job_card(page, 0, "Backend Engineer Acme Applied 5 months ago"),
            _job_card(page, 1, "Data Engineer Acme Easy Apply"),
        ]
    }

    outcome = await browser_tools._task2_on_page(
        page, _settings(tmp_path, post_click_wait_seconds=0), lambda _m: None
    )

    # The applied card is never clicked (no application form opened for it).
    assert page.selected_job == 1
    assert outcome.applied_jobs_skipped == 1
    assert outcome.applied_skipped_cards == [
        {"index": 0, "title": "Backend Engineer Acme Applied 5 months ago"}
    ]
    assert outcome.job_index == 1
    assert outcome.job_title == "Data Engineer Acme Easy Apply"
    assert outcome.easy_apply_clicked is True
    assert outcome.application_form_opened is True


async def test_task2_stops_when_every_card_is_applied(tmp_path) -> None:
    page = FakePage()
    page.by_selector = {
        "li.jobs-search-results__list-item": [
            _job_card(page, 0, "Backend Engineer Acme Applied 5 months ago"),
            _job_card(page, 1, "Data Engineer Acme Applied 2 weeks ago"),
        ]
    }

    outcome = await browser_tools._task2_on_page(
        page, _settings(tmp_path, post_click_wait_seconds=0), lambda _m: None
    )

    assert page.selected_job is None
    assert outcome.applied_jobs_skipped == 2
    assert outcome.easy_apply_clicked is False
    assert outcome.application_form_opened is False
    assert outcome.job_index is None
    assert "no unapplied job found" in outcome.notes


async def test_task2_applied_skip_can_be_disabled(tmp_path) -> None:
    page = FakePage(
        details_apply_labels={0: "Easy Apply to Backend Engineer at Acme"},
    )
    page.by_selector = {
        "li.jobs-search-results__list-item": [
            _job_card(page, 0, "Backend Engineer Acme Applied 5 months ago"),
        ]
    }

    outcome = await browser_tools._task2_on_page(
        page,
        _settings(tmp_path, post_click_wait_seconds=0, skip_applied=False),
        lambda _m: None,
    )

    assert outcome.applied_jobs_skipped == 0
    assert outcome.job_index == 0
    assert outcome.easy_apply_clicked is True
    assert outcome.application_form_opened is True


async def test_read_job_description() -> None:
    page = FakePage()
    description = await browser_tools.read_job_description(page)

    assert description.title == "Backend Engineer"
    assert description.company == "Acme"
    assert description.location == "Remote"
    assert "Python" in description.body
    assert description.page_url == "https://www.linkedin.com/jobs/view/1"
    assert description.is_read is True


async def test_read_job_description_empty_when_pane_missing() -> None:
    page = FakePage(job_description={"title": "", "company": "", "location": "", "body": ""})
    description = await browser_tools.read_job_description(page)
    assert description.is_read is False


async def test_find_easy_apply_filter_prefers_known_selector() -> None:
    filt = FakeElement("Easy Apply filter.")
    page = FakePage(by_selector={"button[aria-label*='Easy Apply']": [filt]})
    assert await browser_tools.find_easy_apply_filter(page) is filt


async def test_find_easy_apply_filter_none_when_absent() -> None:
    page = FakePage(
        by_selector={"button, [role='button']": [FakeElement("Save"), FakeElement("Date posted")]}
    )
    assert await browser_tools.find_easy_apply_filter(page) is None


async def test_select_easy_apply_filter_clicks(tmp_path) -> None:
    page = FakePage()
    filt = _filter_element(page)
    page.by_selector = {"button[aria-label*='Easy Apply']": [filt]}

    selected, note = await browser_tools.select_easy_apply_filter(
        page, _settings(tmp_path, post_click_wait_seconds=0)
    )
    assert selected is True
    assert note == ""
    assert filt.clicked is True


async def test_select_easy_apply_filter_falls_back_to_url(tmp_path) -> None:
    page = FakePage(filter_selected=False)
    page.current_url = SEARCH_URL
    # No filter control in the DOM, so the f_AL=true fallback must be used.
    selected, _ = await browser_tools.select_easy_apply_filter(
        page, _settings(tmp_path, post_click_wait_seconds=0)
    )
    assert selected is True
    assert any("f_AL=true" in url for url in page.goto_calls)


async def test_find_ai_job_search_button_present() -> None:
    button = FakeElement("Try AI job search")
    page = FakePage(ai_buttons=[FakeElement("Save this search"), button])
    # The first candidate merely mentions "search"; the AI one must win.
    assert await browser_tools.find_ai_job_search_button(page) is button


async def test_find_ai_job_search_button_absent() -> None:
    page = FakePage(
        ai_buttons=[FakeElement("Save this search"), FakeElement("Search jobs")]
    )
    assert await browser_tools.find_ai_job_search_button(page) is None


async def test_ai_job_search_query_scans_varied_markup() -> None:
    # The runtime scan must not rely on a plain <button>: LinkedIn may render the
    # entry point as a link/role=button/role=link, with its label spread across
    # aria-label, visible text, value, or title.
    query = browser_tools._AI_CANDIDATES_QUERY
    assert 'role="link"' in query
    assert 'role="button"' in query
    assert "aria-label" in query
    assert "innerText" in query
    assert "value" in query


async def test_click_ai_job_search_clicks_when_present(tmp_path) -> None:
    button = FakeElement("Try AI job search")
    page = FakePage(ai_buttons=[button])

    clicked = await browser_tools.click_ai_job_search(
        page, _settings(tmp_path, post_click_wait_seconds=0)
    )

    assert clicked is True
    assert button.clicked is True
    assert button.scrolled is True


async def test_click_ai_job_search_returns_false_when_absent(tmp_path) -> None:
    page = FakePage()
    clicked = await browser_tools.click_ai_job_search(
        page, _settings(tmp_path, post_click_wait_seconds=0)
    )
    assert clicked is False


async def test_click_ai_job_search_treats_navigation_as_clicked(tmp_path) -> None:
    page = FakePage()

    def _navigate() -> None:
        page.current_url = "https://www.linkedin.com/jobs/ai-search/"

    # A click that navigates can raise *after* the navigation already started
    # (the CDP execution context is destroyed). It must still count as clicked.
    button = FakeElement(
        "Try AI job search",
        on_click=_navigate,
        click_error=RuntimeError("Execution context was destroyed"),
    )
    page.ai_buttons = [button]

    clicked = await browser_tools.click_ai_job_search(
        page, _settings(tmp_path, post_click_wait_seconds=0)
    )

    assert clicked is True
    assert button.clicked is True
    assert page.current_url == "https://www.linkedin.com/jobs/ai-search/"


async def test_click_ai_job_search_waits_for_the_page_to_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage()
    page.ai_buttons = [FakeElement("Try AI job search")]

    waits: list[float] = []

    async def fake_wait(_page, timeout_seconds):
        waits.append(timeout_seconds)
        return True

    monkeypatch.setattr(linkedin_tools, "_wait_for_load", fake_wait)

    clicked = await browser_tools.click_ai_job_search(
        page, _settings(tmp_path, post_click_wait_seconds=0)
    )

    assert clicked is True
    # The click may navigate/reload, so the page load must be awaited after it.
    assert waits


async def test_wait_for_ai_job_search_button_finds_late_button(tmp_path) -> None:
    late = FakeElement("Try AI job search")
    # Nothing on the first scan; the button renders on a later poll.
    page = FakePage(ai_buttons_queue=[[], [late]])

    button = await browser_tools.wait_for_ai_job_search_button(
        page, _settings(tmp_path, ai_search_timeout_seconds=2.0)
    )

    assert button is late


async def test_wait_for_ai_job_search_button_times_out(tmp_path) -> None:
    page = FakePage(ai_buttons=[])

    button = await browser_tools.wait_for_ai_job_search_button(
        page, _settings(tmp_path, ai_search_timeout_seconds=0.05)
    )
    assert button is None


async def test_run_task1_clicks_try_ai_job_search_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)
    ai_button = FakeElement("Try AI job search")
    filt = _filter_element(page)
    # The button is present once, then gone after the click; click it once.
    page.ai_buttons_queue = [[ai_button], []]
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [filt],
    }
    session = FakeSession(page)
    monkeypatch.setattr(linkedin_tools, "build_browser", lambda settings: session)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert outcome.ai_job_search_present is True
    assert outcome.ai_job_search_clicked is True
    assert outcome.ai_job_search_clicks == 1
    assert ai_button.clicked is True
    assert outcome.easy_apply_filter_selected is True
    assert outcome.screenshot_path is None


async def test_run_task1_repeats_search_after_ai_job_search(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)
    ai_button = FakeElement("Try AI job search")
    filt = _filter_element(page)
    page.ai_buttons_queue = [[ai_button], []]
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [filt],
    }
    session = FakeSession(page)
    monkeypatch.setattr(linkedin_tools, "build_browser", lambda settings: session)

    calls: list[str] = []

    async def fake_search(_page, query, _settings, **_kwargs):
        calls.append(query)
        return True, 25, SEARCH_URL

    monkeypatch.setattr(linkedin_tools, "open_jobs_search", fake_search)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert ai_button.clicked is True
    # The search is performed once, then again after the AI job search click.
    assert calls == ["software engineer", "software engineer"]
    assert outcome.results_found is True
    assert outcome.easy_apply_filter_selected is True


async def test_run_task1_stays_in_ai_mode_when_repeat_returns_no_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """After "Try AI job search" is clicked, never fall back to the classic search.

    LinkedIn's AI mode can render no job cards; a repeat search that returns
    nothing simply ends the re-click loop and the outcome reflects the AI search.
    The classic "software engineer" URL must not be opened again.
    """
    page = FakePage(results_count=14)
    ai_button = FakeElement("Try AI job search")
    filt = _filter_element(page)
    page.ai_buttons_queue = [[ai_button], []]
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [filt],
    }
    session = FakeSession(page)
    monkeypatch.setattr(linkedin_tools, "build_browser", lambda settings: session)

    calls: list[str] = []

    async def fake_search(_page, query, _settings, **_kwargs):
        calls.append(query)
        if len(calls) == 1:
            return True, 14, SEARCH_URL
        # The AI mode page the click left behind has no job cards.
        return (
            False,
            0,
            "https://www.linkedin.com/jobs/search-results/?origin=SEMANTIC_SEARCH_MODE_FROM_CLASSIC",
        )

    monkeypatch.setattr(linkedin_tools, "open_jobs_search", fake_search)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert outcome.ai_job_search_clicked is True
    # The initial search plus exactly one repeat; the loop stops there.
    assert calls == ["software engineer", "software engineer"]
    # No fallback to the classic search URL; the outcome reflects the AI mode.
    assert SEARCH_URL not in page.goto_calls
    assert outcome.results_found is False
    assert outcome.results_count == 0


async def test_run_task1_repeats_search_when_ai_click_navigates(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)

    def _navigate() -> None:
        page.current_url = "https://www.linkedin.com/jobs/ai-search/"

    ai_button = FakeElement(
        "Try AI job search",
        on_click=_navigate,
        click_error=RuntimeError("Execution context was destroyed"),
    )
    filt = _filter_element(page)
    page.ai_buttons_queue = [[ai_button], []]
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [filt],
    }
    session = FakeSession(page)
    monkeypatch.setattr(linkedin_tools, "build_browser", lambda settings: session)

    calls: list[str] = []

    async def fake_search(_page, query, _settings, **_kwargs):
        calls.append(query)
        return True, 25, SEARCH_URL

    monkeypatch.setattr(linkedin_tools, "open_jobs_search", fake_search)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert outcome.ai_job_search_clicked is True
    assert calls == ["software engineer", "software engineer"]
    assert outcome.easy_apply_filter_selected is True


async def test_run_task1_reclicks_ai_job_search_while_it_reappears(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)
    ai_button = FakeElement("Try AI job search")
    filt = _filter_element(page)
    # The button never goes away; the loop must stop at the safety cap.
    page.ai_buttons = [ai_button]
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [filt],
    }
    session = FakeSession(page)
    monkeypatch.setattr(linkedin_tools, "build_browser", lambda settings: session)

    calls: list[str] = []

    async def fake_search(_page, query, _settings, **_kwargs):
        calls.append(query)
        return True, 25, SEARCH_URL

    monkeypatch.setattr(linkedin_tools, "open_jobs_search", fake_search)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert outcome.ai_job_search_clicks == browser_tools._MAX_AI_JOB_SEARCH_CLICKS
    # The search runs once initially and once after each AI click.
    assert calls == ["software engineer"] * (1 + browser_tools._MAX_AI_JOB_SEARCH_CLICKS)
    assert outcome.easy_apply_filter_selected is True


async def test_run_task1_stops_reclicking_when_ai_button_disappears(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)
    ai_button = FakeElement("Try AI job search")
    filt = _filter_element(page)
    # Present for two clicks, then gone; the loop stops on its own.
    page.ai_buttons_queue = [[ai_button], [ai_button], []]
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [filt],
    }
    session = FakeSession(page)
    monkeypatch.setattr(linkedin_tools, "build_browser", lambda settings: session)

    calls: list[str] = []

    async def fake_search(_page, query, _settings, **_kwargs):
        calls.append(query)
        return True, 25, SEARCH_URL

    monkeypatch.setattr(linkedin_tools, "open_jobs_search", fake_search)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert outcome.ai_job_search_clicks == 2
    assert calls == ["software engineer", "software engineer", "software engineer"]
    assert outcome.easy_apply_filter_selected is True


async def test_run_task1_records_ai_search_candidates_when_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)
    filt = _filter_element(page)
    # No AI control; only search-related controls are visible. Their labels must
    # be recorded so a real-run miss is diagnosable.
    page.ai_buttons = [FakeElement("Save this search"), FakeElement("Search jobs")]
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [filt],
    }
    session = FakeSession(page)
    monkeypatch.setattr(linkedin_tools, "build_browser", lambda settings: session)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert outcome.ai_job_search_present is False
    assert outcome.ai_job_search_candidates == ["Save this search", "Search jobs"]
    assert "controls seen" in outcome.notes


async def test_run_task1_does_not_repeat_search_without_ai_button(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)
    filt = _filter_element(page)
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [filt],
    }
    session = FakeSession(page)
    monkeypatch.setattr(linkedin_tools, "build_browser", lambda settings: session)

    calls: list[str] = []

    async def fake_search(_page, query, _settings):
        calls.append(query)
        return True, 25, SEARCH_URL

    monkeypatch.setattr(linkedin_tools, "open_jobs_search", fake_search)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert calls == ["software engineer"]
    assert outcome.ai_job_search_clicked is False
    assert outcome.easy_apply_filter_selected is True


async def test_run_task1_succeeds_without_ai_job_search_button(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)
    filt = _filter_element(page)
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [filt],
    }
    session = FakeSession(page)
    monkeypatch.setattr(linkedin_tools, "build_browser", lambda settings: session)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert outcome.ai_job_search_present is False
    assert outcome.ai_job_search_clicked is False
    assert outcome.easy_apply_filter_selected is True
    assert outcome.screenshot_path is None


async def test_run_task1_success(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    page = FakePage(results_count=25)
    filt = _filter_element(page)
    search_field = FakeElement("Search by title, skill, or company")
    submit = FakeElement("Search")
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [search_field],
        "button.jobs-search-box__submit-button": [submit],
        "button[aria-label*='Easy Apply']": [filt],
    }
    session = FakeSession(page)
    messages: list[str] = []

    monkeypatch.setattr(linkedin_tools, "build_browser", lambda settings: session)
    settings = _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL, "software engineer", settings, progress=messages.append
    )

    assert outcome.already_logged_in is True
    assert outcome.logged_in is True
    assert outcome.search_performed is True
    assert outcome.results_found is True
    assert outcome.results_count == 25
    assert outcome.easy_apply_filter_selected is True
    assert outcome.screenshot_path is None
    assert page.goto_calls[0] == DEFAULT_LOGIN_URL
    # The search bar is already present, so the Jobs tab is not reopened.
    assert browser_tools._JOBS_TAB_URL not in page.goto_calls
    assert search_field.filled == "software engineer"
    assert submit.clicked is True
    assert session.started is True and session.killed is True
    assert messages  # progress was reported


async def test_run_task1_paces_each_step_when_step_delay_is_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=25)
    filt = _filter_element(page)
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [filt],
    }
    session = FakeSession(page)
    monkeypatch.setattr(linkedin_tools, "build_browser", lambda settings: session)

    paced: list[float] = []

    async def fake_pace(settings):
        paced.append(settings.session.step_delay_seconds)

    monkeypatch.setattr(linkedin_tools, "_pace", fake_pace)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, step_delay_seconds=0.5, post_click_wait_seconds=0),
    )

    assert outcome.easy_apply_filter_selected is True
    # Every visible step is paced so a human can follow the run.
    assert paced
    assert all(delay == 0.5 for delay in paced)


async def test_run_task1_captures_screenshot_when_login_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(login_payload={"path": "/login", "nav": False, "loginForm": True})
    session = FakeSession(page)

    monkeypatch.setattr(linkedin_tools, "build_browser", lambda settings: session)

    async def fake_wait(_page, *, timeout_seconds, poll_seconds):
        return False

    monkeypatch.setattr(linkedin_tools, "wait_for_login", fake_wait)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL, "software engineer", _settings(tmp_path)
    )

    assert outcome.logged_in is False
    assert outcome.search_performed is False
    assert outcome.screenshot_path is not None
    assert Path(outcome.screenshot_path).is_file()
    assert session.killed is True


async def test_run_task1_captures_screenshot_when_search_is_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=0)
    session = FakeSession(page)

    monkeypatch.setattr(linkedin_tools, "build_browser", lambda settings: session)

    async def fake_search(_page, _query, _settings):
        return False, 0, SEARCH_URL

    monkeypatch.setattr(linkedin_tools, "open_jobs_search", fake_search)

    outcome = await browser_tools.run_task1(
        DEFAULT_LOGIN_URL, "software engineer", _settings(tmp_path)
    )

    assert outcome.logged_in is True
    assert outcome.search_performed is True
    assert outcome.results_found is False
    assert outcome.easy_apply_filter_selected is False
    assert outcome.screenshot_path is not None
    assert session.killed is True


async def test_run_agent_runs_both_tasks(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    page = FakePage(
        results_count=25,
        details_apply_labels={0: "Easy Apply to Backend Engineer at Acme"},
    )
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [_filter_element(page)],
        "li.jobs-search-results__list-item": [_job_card(page, 0, "Backend Engineer")],
    }
    session = FakeSession(page)
    monkeypatch.setattr(browser_tools, "build_browser", lambda settings: session)

    result = await browser_tools.run_agent(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert result.task1.logged_in is True
    assert result.task1.easy_apply_filter_selected is True
    assert result.task2.job_title == "Backend Engineer"
    assert result.task2.easy_apply_clicked is True
    assert result.task2.application_form_opened is True
    assert result.task2.screenshot_path is None
    assert result.job_description.title == "Backend Engineer"
    assert session.started is True and session.killed is True


async def test_run_agent_skips_task2_when_task1_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(login_payload={"path": "/login", "nav": False, "loginForm": True})
    session = FakeSession(page)
    monkeypatch.setattr(browser_tools, "build_browser", lambda settings: session)

    async def fake_wait(_page, *, timeout_seconds, poll_seconds):
        return False

    monkeypatch.setattr(linkedin_tools, "wait_for_login", fake_wait)

    result = await browser_tools.run_agent(
        DEFAULT_LOGIN_URL, "software engineer", _settings(tmp_path)
    )

    assert result.task1.logged_in is False
    assert result.task2.easy_apply_clicked is False
    assert "skipped" in result.task2.notes.lower()
    assert result.task1.screenshot_path is not None
    assert session.killed is True


async def test_run_agent_captures_screenshot_when_apply_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(results_count=5, details_apply_labels={0: "Apply on company website"})
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [_filter_element(page)],
        "li.jobs-search-results__list-item": [_job_card(page, 0, "External Job")],
    }
    session = FakeSession(page)
    monkeypatch.setattr(browser_tools, "build_browser", lambda settings: session)

    result = await browser_tools.run_agent(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert result.task1.easy_apply_filter_selected is True
    assert result.task2.easy_apply_clicked is False
    assert result.task2.screenshot_path is not None
    assert session.killed is True


async def test_enumerate_form_fields() -> None:
    page = FakePage(
        form_enumerations=[
            {"open": True, "fields": [{"marker": "f0", "kind": "input", "question": "Name"}]}
        ]
    )
    opened, fields = await browser_tools.enumerate_form_fields(page)

    assert opened is True
    assert fields[0]["marker"] == "f0"


async def test_enumerate_form_fields_reports_closed_form() -> None:
    opened, fields = await browser_tools.enumerate_form_fields(FakePage())
    assert opened is False
    assert fields == []


def _text_field(marker: str, name: str, question: str, *, required: bool = False) -> dict:
    return {
        "marker": marker,
        "kind": "input",
        "type": "text",
        "name": name,
        "question": question,
        "option": "",
        "required": required,
        "checked": False,
        "value": "",
        "options": [],
    }


async def test_task4_fills_form_and_selects_listed_resume(tmp_path) -> None:
    fields = [
        _text_field("f0", "phone", "Phone number", required=True),
        _text_field("f1", "city", "City"),
        {
            "marker": "f2",
            "kind": "radio",
            "type": "radio",
            "name": "work_auth",
            "question": "Are you authorised to work in Australia?",
            "option": "Yes",
            "required": True,
            "checked": False,
            "value": "",
            "options": [],
        },
        {
            "marker": "f3",
            "kind": "radio",
            "type": "radio",
            "name": "work_auth",
            "question": "Are you authorised to work in Australia?",
            "option": "No",
            "required": True,
            "checked": False,
            "value": "",
            "options": [],
        },
        {
            "marker": "f4",
            "kind": "select",
            "type": "select",
            "name": "experience",
            "question": "Years of experience",
            "option": "",
            "required": False,
            "checked": False,
            "value": "",
            "options": [{"value": "5", "text": "5"}],
        },
    ]
    page = FakePage(
        form_enumerations=[{"open": True, "fields": fields}],
        form_buttons_queue=[[{"marker": "b0", "text": "Submit application", "disabled": False}]],
        resume_options={
            "options": [
                {
                    "marker": "r0",
                    "label": "ShaktiKC_Resume_python_Node_Senior.pdf",
                    "value": "",
                    "checked": False,
                }
            ],
            "fileInput": True,
        },
    )
    page.fill_elements = {
        "f0": FakeElement("Phone number"),
        "f1": FakeElement("City"),
        "f2": FakeElement("Yes"),
        "f3": FakeElement("No"),
        "f4": FakeElement("Years of experience"),
    }
    page.resume_elements = {"r0": FakeElement("ShaktiKC_Resume_python_Node_Senior.pdf")}
    page.button_elements = {"b0": FakeElement("Submit application")}
    answers = {
        "phone number": "+61 400 000 000",
        "are you authorised to work in australia": "Yes",
        "years of experience": "5",
    }

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        "resumes/ShaktiKC_Resume_python_Node_Senior.pdf",
        answers,
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
        chooser=_store_chooser(answers),
    )

    assert outcome.form_open is True
    assert outcome.fields_enumerated == 5
    assert outcome.known_fields == 3
    assert outcome.filled_fields == 3
    assert outcome.unknown_fields == ["City"]
    assert page.fill_elements["f0"].filled == "+61 400 000 000"
    assert page.fill_elements["f2"].clicked is True
    assert page.fill_elements["f3"].clicked is False
    assert page.fill_elements["f4"].selected_option == "5"
    assert outcome.resume_attached is True
    assert outcome.resume_selection == "listed"
    assert page.resume_elements["r0"].clicked is True
    # Each LLM (Task 4.1) decision records the classification, chosen key, and why.
    llm_fields = [f for f in outcome.fields if f.answered_by == "llm"]
    assert llm_fields
    assert all(
        f.question_type == "test" and f.matched_key and f.rationale == "test chooser"
        for f in llm_fields
    )
    # The one available button is Submit; it must never be clicked.
    assert outcome.submitted is False
    assert outcome.steps_advanced == 0
    assert page.button_elements["b0"].clicked is False


async def test_task4_uploads_resume_when_not_listed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(
        form_enumerations=[{"open": True, "fields": [_text_field("f0", "phone", "Phone number")]}],
        form_buttons_queue=[[]],
        resume_options={
            "options": [
                {"marker": "r0", "label": "Some_Other_Resume.pdf", "value": "", "checked": False}
            ],
            "fileInput": True,
        },
    )
    page.fill_elements = {"f0": FakeElement("Phone number")}
    page.file_element = FakeElement("file")

    uploaded: dict = {}

    async def fake_upload(session, page, selector: str, path: str) -> None:
        uploaded["selector"] = selector
        uploaded["path"] = path

    monkeypatch.setattr(fill_tools, "upload_file_via_cdp", fake_upload)

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        "resumes/ShaktiKC_Resume_python_Node_Senior.pdf",
        {},
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
    )

    assert outcome.upload_attempted is True
    assert outcome.resume_attached is True
    assert outcome.resume_selection == "uploaded"
    assert uploaded["path"].endswith("ShaktiKC_Resume_python_Node_Senior.pdf")
    assert uploaded["selector"] == '[data-autojob-file="1"]'


async def test_task4_advances_steps_but_never_submits(tmp_path) -> None:
    page = FakePage(
        form_enumerations=[
            {"open": True, "fields": [_text_field("f0", "phone", "Phone number")]},
            {"open": True, "fields": [_text_field("f1", "city", "City")]},
        ],
        form_buttons_queue=[
            [{"marker": "b0", "text": "Next", "disabled": False}],
            [{"marker": "b1", "text": "Submit application", "disabled": False}],
        ],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {"f0": FakeElement("Phone number"), "f1": FakeElement("City")}
    page.button_elements = {
        "b0": FakeElement("Next"),
        "b1": FakeElement("Submit application"),
    }

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        "resumes/ShaktiKC_Resume_python_Node_Senior.pdf",
        {"phone number": "+61", "city": "Sydney"},
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
        chooser=_store_chooser({"phone number": "+61", "city": "Sydney"}),
    )

    assert outcome.steps_advanced == 1
    assert page.button_elements["b0"].clicked is True
    assert page.button_elements["b1"].clicked is False
    assert outcome.submitted is False
    assert outcome.known_fields == 2
    assert outcome.filled_fields == 2
    assert outcome.resume_attached is False
    assert "no resume control" in outcome.notes


def _contact_step_fields() -> list[dict]:
    """A required Contact-info step: email select, country select, phone input."""
    return [
        {
            "marker": "f0",
            "kind": "select",
            "type": "select",
            "name": "email",
            "question": "Email address",
            "option": "",
            "required": True,
            "checked": False,
            "value": "",
            "options": [{"value": "me@example.com", "text": "me@example.com"}],
        },
        {
            "marker": "f1",
            "kind": "select",
            "type": "select",
            "name": "country",
            "question": "Phone country code",
            "option": "",
            "required": True,
            "checked": False,
            "value": "",
            "options": [{"value": "Australia (+61)", "text": "Australia (+61)"}],
        },
        _text_field("f2", "phone", "Mobile phone number", required=True),
    ]


async def test_task4_follows_dynamic_form_and_selects_resume_from_select(tmp_path) -> None:
    """The resume may be on any step and rendered as a <select>, not a radio."""
    page = FakePage(
        form_enumerations=[
            {"open": True, "title": "Contact info", "fields": _contact_step_fields()},
            {"open": True, "title": "Resume", "fields": []},
        ],
        form_buttons_queue=[[{"marker": "b0", "text": "Next", "disabled": False}], []],
        resume_options=[
            {"options": [], "fileInput": False, "select": None, "uploadButton": None},
            {
                "options": [],
                "fileInput": False,
                "uploadButton": None,
                "select": {
                    "marker": "s0",
                    "label": "Select a resume",
                    "options": [
                        {"value": "other", "text": "Other_Resume.pdf"},
                        {"value": "chosen", "text": "ShaktiKC_Resume_python_Node_Senior.pdf"},
                    ],
                },
            },
        ],
    )
    page.fill_elements = {
        "f0": FakeElement("Email address"),
        "f1": FakeElement("Phone country code"),
        "f2": FakeElement("Mobile phone number"),
    }
    page.select_elements = {"s0": FakeElement("Select a resume")}
    page.button_elements = {"b0": FakeElement("Next")}

    answers = {
        "email address": "me@example.com",
        "phone country code": "Australia (+61)",
        "mobile phone number": "400000000",
    }
    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        "resumes/ShaktiKC_Resume_python_Node_Senior.pdf",
        answers,
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
        chooser=_store_chooser(answers),
    )

    assert outcome.form_open is True
    assert outcome.steps_advanced == 1
    assert outcome.resume_attached is True
    assert outcome.resume_selection == "listed"
    assert outcome.resume_listed_name == "ShaktiKC_Resume_python_Node_Senior.pdf"
    assert page.select_elements["s0"].selected_option == "chosen"
    assert outcome.submitted is False


async def test_task4_clicks_upload_button_to_reveal_file_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """When no resume control is visible, an Upload button may reveal the input."""
    page = FakePage(
        form_enumerations=[{"open": True, "title": "Resume", "fields": []}],
        form_buttons_queue=[[]],
        resume_options=[
            {
                "options": [],
                "fileInput": False,
                "select": None,
                "uploadButton": {"marker": "u0", "label": "Upload resume"},
            },
            {"options": [], "fileInput": True, "select": None, "uploadButton": None},
        ],
    )
    page.upload_elements = {
        "u0": FakeElement(
            "Upload resume",
            on_click=lambda: setattr(page, "file_element", FakeElement("file")),
        )
    }

    uploaded: dict = {}

    async def fake_upload(session, page, selector: str, path: str) -> None:
        uploaded["selector"] = selector
        uploaded["path"] = path

    monkeypatch.setattr(fill_tools, "upload_file_via_cdp", fake_upload)

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        "resumes/ShaktiKC_Resume_python_Node_Senior.pdf",
        {},
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
    )

    assert page.upload_elements["u0"].clicked is True
    assert outcome.resume_attached is True
    assert outcome.resume_selection == "uploaded"
    assert uploaded["path"].endswith("ShaktiKC_Resume_python_Node_Senior.pdf")


async def test_task4_stops_when_dynamic_form_does_not_advance(tmp_path) -> None:
    """A required unknown field blocks Next; stop instead of re-clicking forever."""
    fields = _contact_step_fields()
    page = FakePage(
        form_enumerations=[
            {"open": True, "title": "Contact info", "fields": fields},
            {"open": True, "title": "Contact info", "fields": fields},
            {"open": True, "title": "Contact info", "fields": fields},
        ],
        form_buttons_queue=[
            [{"marker": "b0", "text": "Next", "disabled": False}] for _ in range(3)
        ],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {
        "f0": FakeElement("Email address"),
        "f1": FakeElement("Phone country code"),
        "f2": FakeElement("Mobile phone number"),
    }
    page.button_elements = {"b0": FakeElement("Next")}

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        None,
        {},
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
    )

    # A step that did not actually advance must not be counted as advanced.
    assert outcome.steps_advanced == 0
    assert "did not advance" in outcome.notes
    # The note names the required answers that blocked Next, for a clear stop.
    assert "Email address" in outcome.notes
    assert "Mobile phone number" in outcome.notes
    # It tried once and stopped (no blind retry loop).
    assert page.button_elements["b0"].clicked is True


async def test_task4_stops_clearly_when_next_is_disabled(tmp_path) -> None:
    """A disabled Next (required answer unknown) stops with a clear, named note."""
    fields = _contact_step_fields()  # all required, none answered
    page = FakePage(
        form_enumerations=[{"open": True, "title": "Contact info", "fields": fields}],
        form_buttons_queue=[[{"marker": "b0", "text": "Next", "disabled": True}]],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {
        "f0": FakeElement("Email address"),
        "f1": FakeElement("Phone country code"),
        "f2": FakeElement("Mobile phone number"),
    }
    page.button_elements = {"b0": FakeElement("Next")}

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        None,
        {},
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
    )

    assert outcome.steps_advanced == 0
    assert outcome.submitted is False
    assert page.button_elements["b0"].clicked is False
    assert "disabled" in outcome.notes
    assert "Email address" in outcome.notes
    assert "stopping before Submit" in outcome.notes


async def test_task4_reports_missing_form(tmp_path) -> None:
    page = FakePage(form_open_default=False)

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        "resumes/a.pdf",
        {},
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
    )

    assert outcome.form_open is False
    assert "form was not found" in outcome.notes


def test_task4_form_queries_ignore_hidden_dialogs() -> None:
    """All Task 4 queries pick the visible Easy Apply modal, not merely the first match.

    A real jobs page can carry an unrelated hidden ``.artdeco-modal`` (e.g.
    "Save this job") earlier in the DOM. A bare ``document.querySelector`` would
    pick it, enumerate zero fields, and fill nothing, so every Task 4 query must
    resolve the modal through the shared visibility-aware helper.
    """
    queries = {
        "enumerate": fill_tools._ENUMERATE_FORM_QUERY,
        "resume": fill_tools._RESUME_OPTIONS_QUERY,
        "buttons": fill_tools._FORM_BUTTONS_QUERY,
    }
    for name, query in queries.items():
        assert "findApplyRoot" in query, f"{name} query lost the form finder"
        assert "getClientRects" in query, f"{name} query no longer checks visibility"
        assert "const modal = document.querySelector(" not in query, name


def test_task2_apply_modal_query_uses_shared_form_finder() -> None:
    """Task 2 must detect both the classic modal and the inline semantic form."""
    query = browser_tools._APPLY_MODAL_QUERY
    assert "findApplyRoot" in query
    assert "getClientRects" in query


def _radio_field(
    marker: str, name: str, question: str, option: str, *, required: bool = False
) -> dict:
    return {
        "marker": marker,
        "kind": "radio",
        "type": "radio",
        "name": name,
        "question": question,
        "option": option,
        "required": required,
        "checked": False,
        "value": "",
        "options": [],
    }


def _human_asker(
    monkeypatch: pytest.MonkeyPatch,
    answer: str | None,
    calls: list[str],
) -> None:
    """Patch the Task 5 browser prompt with a canned answer (None = skip)."""

    async def fake_ask(page, question, field_type, hint, settings, notify, task5=None):
        calls.append(question)
        if task5 is not None:
            task5.asked += 1
            if answer is None:
                task5.skipped += 1
            else:
                task5.answered += 1
                if question not in task5.answered_questions:
                    task5.answered_questions.append(question)
        return answer

    monkeypatch.setattr(fill_tools, "ask_human_for_answer", fake_ask)


def _store_chooser(answers: dict[str, str]):
    """Stand in for the Task 4.1 LLM: choose the stored answer that fits.

    It reads ``answers`` live, so an answer Task 5 just remembered is reused on
    the next step exactly as the real model would reuse it.
    """

    async def choose(question: str, field_type: str, options: list[str]) -> QuestionDecision:
        key = normalize_question(question)
        for stored_key, value in answers.items():
            if stored_key == key or (stored_key and stored_key in key):
                return QuestionDecision(
                    question=question,
                    category="test",
                    answer=value,
                    matched_key=stored_key,
                    rationale="test chooser",
                )
        return QuestionDecision(question=question)

    return choose


async def test_task5_asks_human_and_remembers_the_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """An unknown question is asked once, filled, stored, and reused from the store."""
    page = FakePage(
        form_enumerations=[
            {"open": True, "title": "Step 1", "fields": [_text_field("f0", "city", "City")]},
            {"open": True, "title": "Step 2", "fields": [_text_field("f1", "city", "City")]},
        ],
        form_buttons_queue=[
            [{"marker": "b0", "text": "Next", "disabled": False}],
            [{"marker": "b1", "text": "Submit application", "disabled": False}],
        ],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {"f0": FakeElement("City"), "f1": FakeElement("City")}
    page.button_elements = {"b0": FakeElement("Next"), "b1": FakeElement("Submit application")}
    calls: list[str] = []
    human = Task5Outcome()
    _human_asker(monkeypatch, "Sydney", calls)
    answers: dict[str, str] = {}
    settings = _settings(tmp_path, ask_human=True, post_click_wait_seconds=0)

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        None,
        answers,
        settings,
        lambda _m: None,
        human=human,
        chooser=_store_chooser(answers),
    )

    # Asked exactly once: step 2 reused the remembered answer with no prompt.
    assert calls == ["City"]
    assert human.enabled is True
    assert human.asked == 1
    assert human.answered == 1
    assert human.answered_questions == ["City"]

    assert page.fill_elements["f0"].filled == "Sydney"
    assert page.fill_elements["f1"].filled == "Sydney"
    assert outcome.known_fields == 2
    assert outcome.filled_fields == 2
    assert outcome.unknown_fields == []
    assert outcome.submitted is False
    # The first record came from the human, the repeat from the LLM (which now
    # finds the remembered answer in the store).
    assert [r.answered_by for r in outcome.fields if r.question == "City"] == ["human", "llm"]

    # Persisted (normalized) and updated in memory for the rest of this run.
    assert browser_tools.load_answers(settings.answers_file)["city"] == "Sydney"
    assert answers["city"] == "Sydney"


async def test_task5_human_skip_leaves_the_question_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(
        form_enumerations=[{"open": True, "fields": [_text_field("f0", "city", "City")]}],
        form_buttons_queue=[[{"marker": "b0", "text": "Submit application", "disabled": False}]],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {"f0": FakeElement("City")}
    page.button_elements = {"b0": FakeElement("Submit application")}
    calls: list[str] = []
    human = Task5Outcome()
    _human_asker(monkeypatch, None, calls)
    settings = _settings(tmp_path, ask_human=True, post_click_wait_seconds=0)

    outcome = await browser_tools._task4_on_page(
        page, FakeSession(page), None, {}, settings, lambda _m: None, human=human
    )

    assert calls == ["City"]
    assert human.asked == 1
    assert human.skipped == 1
    assert outcome.unknown_fields == ["City"]
    assert page.fill_elements["f0"].filled is None
    assert not settings.answers_file.exists()


async def test_task5_is_off_when_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    page = FakePage(
        form_enumerations=[{"open": True, "fields": [_text_field("f0", "city", "City")]}],
        form_buttons_queue=[[{"marker": "b0", "text": "Submit application", "disabled": False}]],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {"f0": FakeElement("City")}
    page.button_elements = {"b0": FakeElement("Submit application")}
    called = False

    async def fake_ask(*args, **kwargs):
        nonlocal called
        called = True
        return "Sydney"

    monkeypatch.setattr(fill_tools, "ask_human_for_answer", fake_ask)
    human = Task5Outcome()

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        None,
        {},
        _settings(tmp_path, post_click_wait_seconds=0),  # ask_human defaults off in tests
        lambda _m: None,
        human=human,
    )

    assert called is False
    assert human.enabled is False
    assert human.asked == 0
    assert outcome.unknown_fields == ["City"]


async def test_task5_answers_a_required_radio_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    fields = [
        _radio_field("f0", "sponsor", "Do you require sponsorship?", "Yes", required=True),
        _radio_field("f1", "sponsor", "Do you require sponsorship?", "No", required=True),
    ]
    page = FakePage(
        form_enumerations=[{"open": True, "fields": fields}],
        form_buttons_queue=[[{"marker": "b0", "text": "Submit application", "disabled": False}]],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {"f0": FakeElement("Yes"), "f1": FakeElement("No")}
    page.button_elements = {"b0": FakeElement("Submit application")}
    calls: list[str] = []
    human = Task5Outcome()
    _human_asker(monkeypatch, "No", calls)
    settings = _settings(tmp_path, ask_human=True, post_click_wait_seconds=0)

    outcome = await browser_tools._task4_on_page(
        page, FakeSession(page), None, {}, settings, lambda _m: None, human=human
    )

    # The human's "No" matched only the "No" option.
    assert calls == ["Do you require sponsorship?"]
    assert page.fill_elements["f0"].clicked is False
    assert page.fill_elements["f1"].clicked is True
    assert outcome.known_fields == 1
    assert outcome.filled_fields == 1
    assert browser_tools.load_answers(settings.answers_file)["do you require sponsorship"] == "No"


async def test_task5_skips_prefilled_controls(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A pre-filled select (e.g. the profile email) is left alone and not asked about."""
    fields = [
        {
            "marker": "f0",
            "kind": "select",
            "type": "select",
            "name": "email",
            "question": "Email address",
            "option": "",
            "required": True,
            "checked": False,
            "value": "me@example.com",
            "options": [{"value": "me@example.com", "text": "me@example.com"}],
        },
        _text_field("f1", "phone", "Mobile phone number", required=True),
    ]
    page = FakePage(
        form_enumerations=[{"open": True, "title": "Contact info", "fields": fields}],
        form_buttons_queue=[[{"marker": "b0", "text": "Submit application", "disabled": False}]],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {
        "f0": FakeElement("Email address"),
        "f1": FakeElement("Mobile phone number"),
    }
    page.button_elements = {"b0": FakeElement("Submit application")}
    calls: list[str] = []
    human = Task5Outcome()
    _human_asker(monkeypatch, "+61 400 000 000", calls)
    settings = _settings(tmp_path, ask_human=True, post_click_wait_seconds=0)

    outcome = await browser_tools._task4_on_page(
        page, FakeSession(page), None, {}, settings, lambda _m: None, human=human
    )

    # Only the genuinely-empty required field was asked; the email select was not.
    assert calls == ["Mobile phone number"]
    assert page.fill_elements["f0"].selected_option is None
    assert page.fill_elements["f1"].filled == "+61 400 000 000"
    assert outcome.unknown_fields == []
    assert [r.answered_by for r in outcome.fields if r.question == "Email address"] == ["form"]
    stored = browser_tools.load_answers(settings.answers_file)
    assert stored.get("mobile phone number") == "+61 400 000 000"
    assert "email address" not in stored


async def test_task5_select_answer_matches_option_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A human may type a select's visible label; it must map to the option value."""
    fields = [
        {
            "marker": "f0",
            "kind": "select",
            "type": "select",
            "name": "contact_method",
            "question": "Preferred contact method",
            "option": "",
            "required": True,
            "checked": False,
            "value": "",
            "options": [
                {"value": "em", "text": "Email"},
                {"value": "ph", "text": "Phone"},
            ],
        }
    ]
    page = FakePage(
        form_enumerations=[{"open": True, "fields": fields}],
        form_buttons_queue=[[{"marker": "b0", "text": "Submit application", "disabled": False}]],
        resume_options={"options": [], "fileInput": False},
    )
    page.fill_elements = {"f0": FakeElement("Preferred contact method")}
    page.button_elements = {"b0": FakeElement("Submit application")}
    calls: list[str] = []
    human = Task5Outcome()
    _human_asker(monkeypatch, "Phone", calls)
    settings = _settings(tmp_path, ask_human=True, post_click_wait_seconds=0)

    outcome = await browser_tools._task4_on_page(
        page, FakeSession(page), None, {}, settings, lambda _m: None, human=human
    )

    assert calls == ["Preferred contact method"]
    # The visible label "Phone" was mapped to the option value "ph".
    assert page.fill_elements["f0"].selected_option == "ph"
    assert outcome.filled_fields == 1
    assert browser_tools.load_answers(settings.answers_file)["preferred contact method"] == "Phone"


class _Task5BannerPage:
    """A minimal page that plays the Task 5 banner and the form-answer watcher."""

    def __init__(self, *, answer: str = "", done: bool = True, skip: bool = False) -> None:
        self.answer = answer
        self.done = done
        self.skip = skip
        self.shown = False
        self.hidden = False

    async def evaluate(self, js: str, *args):
        if "autojob-unknown" in js:
            if "getAttribute" in js:
                state = "skipped" if self.skip else "pending"
                return json.dumps({"present": True, "state": state})
            if "box.remove()" in js:
                self.hidden = True
                return True
            self.shown = True
            return True
        if "__autojobFormAnswer" in js and "addEventListener" in js:
            return True
        if "__autojobFormAnswer" in js:
            return json.dumps({"value": self.answer, "done": self.done})
        return ""


async def test_task5_reads_the_answer_typed_into_the_form(tmp_path) -> None:
    """The banner has no input: the answer is read from the form field the human edits."""
    page = _Task5BannerPage(answer="Sydney", done=True)
    notes: list[str] = []
    human = Task5Outcome()
    settings = _settings(tmp_path, ask_human=True, ask_poll_seconds=0.01)

    answer = await browser_tools.ask_human_for_answer(
        page, "City", "text", "", settings, notes.append, human
    )

    assert answer == "Sydney"
    assert page.shown is True
    assert page.hidden is True
    assert human.asked == 1
    assert human.answered == 1
    assert human.answered_questions == ["City"]
    assert any("City" in note for note in notes)


async def test_task5_empty_form_edit_keeps_waiting(tmp_path) -> None:
    """An empty edit never counts as an answer; the wait times out instead."""
    page = _Task5BannerPage(answer="", done=True)
    human = Task5Outcome()
    settings = _settings(
        tmp_path, ask_human=True, ask_timeout_seconds=0.05, ask_poll_seconds=0.01
    )

    answer = await browser_tools.ask_human_for_answer(
        page, "City", "text", "", settings, lambda _m: None, human
    )

    assert answer is None
    assert human.answered == 0
    assert human.timed_out == 1


async def test_task5_skip_still_leaves_the_question_unknown(tmp_path) -> None:
    """The banner keeps a Skip button; skipping returns no answer."""
    page = _Task5BannerPage(skip=True)
    human = Task5Outcome()
    settings = _settings(tmp_path, ask_human=True, ask_poll_seconds=0.01)

    answer = await browser_tools.ask_human_for_answer(
        page, "City", "text", "", settings, lambda _m: None, human
    )

    assert answer is None
    assert human.skipped == 1
    assert human.answered == 0


async def test_run_agent_registers_and_closes_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(
        results_count=25,
        details_apply_labels={0: "Easy Apply to Backend Engineer at Acme"},
    )
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [_filter_element(page)],
        "li.jobs-search-results__list-item": [_job_card(page, 0, "Backend Engineer")],
    }
    session = FakeSession(page)
    monkeypatch.setattr(browser_tools, "build_browser", lambda settings: session)

    result = await browser_tools.run_agent(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert result.task2.application_form_opened is True
    assert result.job_description.is_read is True
    # run_agent does not fill the form; the graph's fill node does.
    assert result.task4.form_open is False
    assert session.killed is True
    assert browser_tools._ACTIVE_RUNS == {}


async def test_start_tasks_keeps_the_session_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    page = FakePage(
        results_count=25,
        details_apply_labels={0: "Easy Apply to Backend Engineer at Acme"},
    )
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [_filter_element(page)],
        "li.jobs-search-results__list-item": [_job_card(page, 0, "Backend Engineer")],
    }
    session = FakeSession(page)
    monkeypatch.setattr(browser_tools, "build_browser", lambda settings: session)

    _outcome, run_id = await browser_tools.start_tasks(
        DEFAULT_LOGIN_URL,
        "software engineer",
        _settings(tmp_path, login_timeout_seconds=5, post_click_wait_seconds=0),
    )

    assert run_id is not None
    assert session.killed is False
    assert browser_tools.get_run(run_id) is not None

    await browser_tools.close_run(run_id)
    assert session.killed is True
    assert browser_tools.get_run(run_id) is None


async def test_upload_file_via_cdp_rejects_missing_file(tmp_path) -> None:
    with pytest.raises(RuntimeError):
        await browser_tools.upload_file_via_cdp(
            object(), object(), 'input[type="file"]', str(tmp_path / "missing.pdf")
        )


async def test_run_full_agent_end_to_end_offline(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    resume_dir = tmp_path / "resumes"
    resume_dir.mkdir()
    (resume_dir / "ShaktiKC_Resume_python_Node_Senior.txt").write_text(
        "Senior Python engineer. Python, AWS, Docker, 8 years.", encoding="utf-8"
    )
    answers_file = tmp_path / "answers.json"
    answers_file.write_text('{"phone number": "+61 400 000 000"}', encoding="utf-8")

    page = FakePage(
        results_count=25,
        details_apply_labels={0: "Easy Apply to Backend Engineer at Acme"},
        form_enumerations=[{"open": True, "fields": [_text_field("f0", "phone", "Phone number")]}],
        form_buttons_queue=[[{"marker": "b0", "text": "Submit application", "disabled": False}]],
        resume_options={
            "options": [
                {
                    "marker": "r0",
                    "label": "ShaktiKC_Resume_python_Node_Senior.txt",
                    "value": "",
                    "checked": False,
                }
            ],
            "fileInput": True,
        },
    )
    page.by_selector = {
        "input.jobs-search-box__keyboard-text-input": [
            FakeElement("Search by title, skill, or company")
        ],
        "button.jobs-search-box__submit-button": [FakeElement("Search")],
        "button[aria-label*='Easy Apply']": [_filter_element(page)],
        "li.jobs-search-results__list-item": [_job_card(page, 0, "Backend Engineer")],
    }
    page.fill_elements = {"f0": FakeElement("Phone number")}
    page.resume_elements = {"r0": FakeElement("ShaktiKC_Resume_python_Node_Senior.txt")}
    page.button_elements = {"b0": FakeElement("Submit application")}

    session = FakeSession(page)
    monkeypatch.setattr(browser_tools, "build_browser", lambda settings: session)
    # Task 4.1's LLM is a stand-in here (no network in unit tests): it chooses
    # stored answers exactly as the model is expected to.
    monkeypatch.setattr(
        fill_tools, "build_answer_chooser", lambda settings, answers: _store_chooser(answers)
    )

    settings = Settings(
        session=SessionSettings(
            headless=True,
            login_timeout_seconds=5,
            post_click_wait_seconds=0,
            ai_search_timeout_seconds=0,
            ask_human=False,
        ),
        data_dir=tmp_path,
        resumes_dir=resume_dir,
        answers_path=answers_file,
    )

    result = await browser_tools.run_full_agent(DEFAULT_LOGIN_URL, "software engineer", settings)

    assert result.task1.easy_apply_filter_selected is True
    assert result.task2.application_form_opened is True
    assert result.job_description.is_read is True
    assert result.task3.selected_path is not None
    assert result.task3.selected_path.endswith("ShaktiKC_Resume_python_Node_Senior.txt")
    assert result.task4.form_open is True
    assert result.task4.resume_selection == "listed"
    assert result.task4.filled_fields == 1
    assert result.task4.submitted is False
    assert page.button_elements["b0"].clicked is False
    assert session.killed is True
    assert browser_tools._ACTIVE_RUNS == {}


def test_build_browser_creates_profile_dir(tmp_path) -> None:
    pytest.importorskip("browser_use")
    settings = _settings(tmp_path, headless=True)
    browser = browser_tools.build_browser(settings)
    assert browser is not None
    assert settings.profile_dir.is_dir()


def test_clear_profile_locks_removes_singleton_files(tmp_path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    for name in browser_tools._PROFILE_LOCK_FILES:
        (profile / name).write_text("x", encoding="utf-8")
    assert browser_tools._profile_is_locked(profile) is True

    browser_tools._clear_profile_locks(profile)

    assert browser_tools._profile_is_locked(profile) is False
    assert all(not (profile / name).exists() for name in browser_tools._PROFILE_LOCK_FILES)


def test_clean_profile_terminates_and_unlocks(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    settings = Settings(session=SessionSettings(headless=True), data_dir=tmp_path)
    settings.profile_dir.mkdir(parents=True)
    (settings.profile_dir / "lockfile").write_text("", encoding="utf-8")
    calls: list = []

    def fake_terminate(profile_dir):
        calls.append(profile_dir)
        return 2

    monkeypatch.setattr(browser_tools, "terminate_profile_browsers", fake_terminate)

    killed = browser_tools.clean_profile(settings)

    assert killed == 2
    assert calls == [settings.profile_dir]
    assert browser_tools._profile_is_locked(settings.profile_dir) is False


def test_terminate_profile_browsers_kills_each_pid(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(browser_tools, "_profile_browser_pids", lambda _p: [11, 22])
    commands: list = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(browser_tools.subprocess, "run", fake_run)

    assert browser_tools.terminate_profile_browsers(tmp_path) == 2
    assert len(commands) == 2


def test_build_browser_clears_a_stale_profile_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    pytest.importorskip("browser_use")
    settings = Settings(
        session=SessionSettings(headless=True, clean_stale_profile=True),
        data_dir=tmp_path,
    )
    settings.profile_dir.mkdir(parents=True)
    (settings.profile_dir / "lockfile").write_text("", encoding="utf-8")

    # No live browser owns the lock, so it is stale and may be cleared.
    monkeypatch.setattr(browser_tools, "_profile_browser_pids", lambda _p: [])

    browser = browser_tools.build_browser(settings)

    assert browser is not None
    assert browser_tools._profile_is_locked(settings.profile_dir) is False


def test_build_browser_refuses_to_kill_a_live_browser_holding_the_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A second launch must not tear down a browser another run is driving.

    Regression test for the reported failure: force-closing the live browser
    dropped its CDP WebSocket and every reconnect was refused (WinError 1225).
    """
    pytest.importorskip("browser_use")
    settings = Settings(
        session=SessionSettings(headless=True, clean_stale_profile=True),
        data_dir=tmp_path,
    )
    settings.profile_dir.mkdir(parents=True)
    (settings.profile_dir / "lockfile").write_text("", encoding="utf-8")

    # A live browser owns the profile (a running process references it).
    monkeypatch.setattr(browser_tools, "_profile_browser_pids", lambda _p: [4321])
    killed: list = []

    def fake_terminate(profile_dir):
        killed.append(profile_dir)
        return 1

    monkeypatch.setattr(browser_tools, "terminate_profile_browsers", fake_terminate)

    with pytest.raises(RuntimeError, match="already using the AutoJobApply profile"):
        browser_tools.build_browser(settings)

    # The live browser was left untouched, so the other run keeps its CDP link.
    assert killed == []
    assert browser_tools._profile_is_locked(settings.profile_dir) is True


def test_build_browser_skips_cleanup_when_profile_is_free(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    pytest.importorskip("browser_use")
    settings = Settings(session=SessionSettings(headless=True), data_dir=tmp_path)
    calls: list = []

    def fake_terminate(profile_dir):
        calls.append(profile_dir)
        return 0

    monkeypatch.setattr(browser_tools, "terminate_profile_browsers", fake_terminate)

    browser = browser_tools.build_browser(settings)

    assert browser is not None
    assert calls == []
