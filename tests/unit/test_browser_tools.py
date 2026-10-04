"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

import json
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

    async def get_attribute(self, name: str) -> str | None:
        if name == "aria-label" and self.aria_label:
            return self.label
        return None

    async def evaluate(self, js: str, *args) -> str:
        if "scrollIntoView" in js:
            self.scrolled = True
        return self.label

    async def fill(self, value: str, clear: bool = True) -> None:
        self.filled = value

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
        if "aria-pressed" in js:
            return json.dumps({"selected": self.filter_selected})
        return ""

    async def get_elements_by_css_selector(self, selector: str) -> list:
        if selector == "button.jobs-apply-button":
            return [self._apply_button()] if self.selected_job is not None else []
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


def test_build_browser_creates_profile_dir(tmp_path) -> None:
    pytest.importorskip("browser_use")
    settings = _settings(tmp_path, headless=True)
    browser = browser_tools.build_browser(settings)
    assert browser is not None
    assert settings.profile_dir.is_dir()
