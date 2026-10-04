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
    ) -> None:
        self.by_selector = by_selector or {}
        self.login_payload = login_payload or {"path": "/feed/", "nav": True, "loginForm": False}
        self.results_count = results_count
        self.filter_selected = filter_selected
        self.ready = ready
        self.goto_calls: list[str] = []
        self.pressed: list[str] = []
        self.current_url = DEFAULT_LOGIN_URL

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
        if "aria-pressed" in js:
            return json.dumps({"selected": self.filter_selected})
        return ""

    async def get_elements_by_css_selector(self, selector: str) -> list:
        return list(self.by_selector.get(selector, []))


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


def test_build_browser_creates_profile_dir(tmp_path) -> None:
    pytest.importorskip("browser_use")
    settings = _settings(tmp_path, headless=True)
    browser = browser_tools.build_browser(settings)
    assert browser is not None
    assert settings.profile_dir.is_dir()
