"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.configuration import SessionSettings, Settings
from src.state import DEFAULT_LOGIN_URL
from src.tools import browser as browser_tools
from src.tools.linkedin import build_jobs_search_url

SEARCH_URL = build_jobs_search_url("software engineer")


class FakeElement:
    def __init__(self, label: str, *, aria_label: bool = True, on_click=None) -> None:
        self.label = label
        self.aria_label = aria_label
        self.on_click = on_click
        self.clicked = False
        self.scrolled = False
        self.filled: str | None = None
        self.selected_option = None
        self.checked = False

    async def get_attribute(self, name: str) -> str | None:
        if name == "aria-label" and self.aria_label:
            return self.label
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
    ) -> None:
        self.by_selector = by_selector or {}
        self.login_payload = login_payload or {"path": "/feed/", "nav": True, "loginForm": False}
        self.results_count = results_count
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
        ):
            match = re.fullmatch(rf'\[{attribute}="([^"]+)"\]', selector)
            if match:
                element = registry.get(match.group(1))
                return [element] if element is not None else []
        if selector in {'[data-autojob-file="1"]', 'input[type="file"]'}:
            return [self.file_element] if self.file_element is not None else []
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


def _job_card(page: FakePage, index: int, title: str) -> FakeElement:
    """A job card that selects its details pane when clicked."""

    def _select() -> None:
        page.selected_job = index

    return FakeElement(title, on_click=_select)


def _settings(tmp_path, **session) -> Settings:
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
    assert page.goto_calls == [browser_tools._JOBS_TAB_URL]


async def test_type_jobs_search_uses_enter_without_submit_button(tmp_path) -> None:
    field = FakeElement("Search by title, skill, or company")
    page = FakePage(by_selector={"input.jobs-search-box__keyboard-text-input": [field]})
    typed = await browser_tools.type_jobs_search(page, "software engineer", _settings(tmp_path))

    assert typed is True
    assert field.filled == "software engineer"
    assert page.pressed == ["Enter"]


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


async def test_find_easy_apply_filter_prefers_filter_label() -> None:
    job_button = FakeElement("Easy Apply to Backend Engineer at Acme")
    filter_button = FakeElement("Easy Apply filter.")
    page = FakePage(by_selector={"button[aria-label*='Easy Apply']": [job_button, filter_button]})
    # Both match `*='Easy Apply'`; the filter must win over the job's button.
    assert await browser_tools.find_easy_apply_filter(page) is filter_button


async def test_read_job_cards() -> None:
    page = FakePage()
    cards = [_job_card(page, 0, "Backend Engineer"), _job_card(page, 1, "Data Engineer")]
    page.by_selector = {"li.jobs-search-results__list-item": cards}

    assert await browser_tools.read_job_cards(page) == cards
    assert await browser_tools.read_job_cards(FakePage()) == []


async def test_find_job_apply_button_reads_details_pane() -> None:
    page = FakePage(details_apply_labels={2: "Easy Apply to Data Engineer at Acme"})
    page.selected_job = 2

    button, label = await browser_tools.find_job_apply_button(page)
    assert button is not None
    assert label == "Easy Apply to Data Engineer at Acme"


async def test_find_job_apply_button_none_without_selection() -> None:
    assert await browser_tools.find_job_apply_button(FakePage()) == (None, "")


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

    monkeypatch.setattr(browser_tools, "build_browser", lambda settings: session)
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
    assert browser_tools._JOBS_TAB_URL in page.goto_calls
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
    monkeypatch.setattr(browser_tools, "build_browser", lambda settings: session)

    paced: list[float] = []

    async def fake_pace(settings):
        paced.append(settings.session.step_delay_seconds)

    monkeypatch.setattr(browser_tools, "_pace", fake_pace)

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

    monkeypatch.setattr(browser_tools, "build_browser", lambda settings: session)

    async def fake_wait(_page, *, timeout_seconds, poll_seconds):
        return False

    monkeypatch.setattr(browser_tools, "wait_for_login", fake_wait)

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

    monkeypatch.setattr(browser_tools, "build_browser", lambda settings: session)

    async def fake_search(_page, _query, _settings):
        return False, 0, SEARCH_URL

    monkeypatch.setattr(browser_tools, "open_jobs_search", fake_search)

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

    monkeypatch.setattr(browser_tools, "wait_for_login", fake_wait)

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

    monkeypatch.setattr(browser_tools, "upload_file_via_cdp", fake_upload)

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

    outcome = await browser_tools._task4_on_page(
        page,
        FakeSession(page),
        "resumes/ShaktiKC_Resume_python_Node_Senior.pdf",
        {
            "email address": "me@example.com",
            "phone country code": "Australia (+61)",
            "mobile phone number": "400000000",
        },
        _settings(tmp_path, post_click_wait_seconds=0),
        lambda _m: None,
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

    monkeypatch.setattr(browser_tools, "upload_file_via_cdp", fake_upload)

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

    settings = Settings(
        session=SessionSettings(headless=True, login_timeout_seconds=5, post_click_wait_seconds=0),
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
