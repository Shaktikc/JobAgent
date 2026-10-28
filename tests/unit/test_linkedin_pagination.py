"""Unit tests for Task 7's results-pagination helpers."""

from __future__ import annotations

import json
import re

from src.configuration import SessionSettings, Settings
from src.tools import linkedin_pagination
from src.tools.linkedin_pagination import (
    current_page_number,
    go_to_next_page,
    is_next_label,
    next_page_url,
    page_number,
    pick_next_page_control,
)


def _settings(**session) -> Settings:
    session.setdefault("post_click_wait_seconds", 0)
    return Settings(session=SessionSettings(**session))


class _FakeElement:
    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.clicked = False
        self.scrolled = False

    async def evaluate(self, js: str, *args):
        if "scrollIntoView" in js:
            self.scrolled = True
        return True

    async def click(self) -> None:
        self.clicked = True


class _FakePage:
    """Minimal page that answers the pagination and results-signature queries."""

    def __init__(self, *, controls: list[dict], signatures: list[dict]) -> None:
        self.controls = controls
        self.signatures = list(signatures)
        self.elements: dict[str, _FakeElement] = {}

    async def evaluate(self, js: str, *args):
        if "data-autojob-page" in js:
            self.elements = {}
            out = []
            for index, control in enumerate(self.controls):
                marker = f"p{index}"
                self.elements[marker] = _FakeElement(marker)
                out.append(
                    {
                        "marker": marker,
                        "label": control["label"],
                        "disabled": control.get("disabled", False),
                        "current": control.get("current", False),
                    }
                )
            return json.dumps({"found": bool(out), "controls": out})
        if "texts" in js:
            if len(self.signatures) > 1:
                return json.dumps(self.signatures.pop(0))
            return json.dumps(self.signatures[0] if self.signatures else {})
        if "data-autojob-card" in js:
            return json.dumps({"count": 0})
        return ""

    async def get_elements_by_css_selector(self, selector: str) -> list:
        match = re.fullmatch(r'\[data-autojob-page="([^"]+)"\]', selector)
        if match:
            element = self.elements.get(match.group(1))
            return [element] if element is not None else []
        return []


def _control(label: str, *, disabled: bool = False, current: bool = False) -> dict:
    return {"marker": label, "label": label, "disabled": disabled, "current": current}


def test_page_number_parses_labels() -> None:
    assert page_number("1") == 1
    assert page_number("Page 3") == 3
    assert page_number("  page 12 ") == 12
    assert page_number("Next") is None
    assert page_number("") is None


def test_is_next_label_matches_next_not_previous() -> None:
    assert is_next_label("Next")
    assert is_next_label("  next  ")
    assert not is_next_label("Previous")
    assert not is_next_label("Page 2")


def test_current_page_number_reads_the_active_control() -> None:
    controls = [_control("Page 1"), _control("Page 2", current=True), _control("Page 3")]
    assert current_page_number(controls) == 2
    assert current_page_number([_control("Page 1")]) is None


def test_pick_next_page_control_prefers_the_next_button() -> None:
    controls = [
        _control("Page 1", current=True),
        _control("Page 2"),
        _control("Next"),
        _control("Previous"),
    ]
    chosen = pick_next_page_control(controls, current_page=1)
    assert chosen is not None
    assert chosen["label"] == "Next"


def test_pick_next_page_control_uses_page_number_without_a_next_button() -> None:
    controls = [_control("Page 1", current=True), _control("Page 2"), _control("Page 3")]
    chosen = pick_next_page_control(controls, current_page=1)
    assert chosen is not None
    assert chosen["label"] == "Page 2"


def test_pick_next_page_control_skips_a_disabled_next_button() -> None:
    controls = [
        _control("Page 2", current=True),
        _control("Next", disabled=True),
        _control("Page 3"),
    ]
    chosen = pick_next_page_control(controls, current_page=2)
    assert chosen is not None
    assert chosen["label"] == "Page 3"


def test_pick_next_page_control_returns_none_on_the_last_page() -> None:
    controls = [_control("Page 4", current=True), _control("Next", disabled=True)]
    assert pick_next_page_control(controls, current_page=4) is None


def test_pick_next_page_control_returns_none_without_a_next_or_current() -> None:
    # No Next button and no detectable current page: nothing to advance to.
    assert pick_next_page_control([_control("Page 1"), _control("Page 2")], None) is None
    assert pick_next_page_control([], 1) is None


def test_pick_next_page_control_ignores_a_stray_next_outside_the_pager() -> None:
    """BUG-069: a details-pane media carousel "Next" is not the results pager.

    The current LinkedIn results page carries an unrelated ``Next`` control (the
    "Trending employee content" carousel) earlier in the DOM than the results
    pager. When the discovery script tagged the real pager group, the picker must
    stay inside it instead of clicking the carousel — the click that previously
    did nothing and stalled ``next_job``.
    """
    controls = [
        {"marker": "carousel", "label": "Next", "disabled": False,
         "current": False, "pager": False},
        {"marker": "p0", "label": "Page 1", "disabled": False,
         "current": True, "pager": True},
        {"marker": "p1", "label": "Page 2", "disabled": False,
         "current": False, "pager": True},
        {"marker": "pager-next", "label": "Next", "disabled": False,
         "current": False, "pager": True},
    ]
    chosen = pick_next_page_control(controls, current_page=1)
    assert chosen is not None
    assert chosen["marker"] == "pager-next"


def test_pick_next_page_control_without_pager_tags_keeps_all_candidates() -> None:
    """When no pager group was tagged, the original preference is unchanged."""
    controls = [_control("Next"), _control("Page 1", current=True), _control("Page 2")]
    chosen = pick_next_page_control(controls, current_page=1)
    assert chosen is not None
    assert chosen["label"] == "Next"


def test_pagination_query_tags_the_pager_group() -> None:
    """The discovery script marks each control so the picker can scope itself."""
    js = linkedin_pagination._PAGINATION_QUERY
    assert "entry.pager" in js
    assert "group.has(control.el)" in js


async def test_go_to_next_page_clicks_next_and_waits_for_the_change() -> None:
    page = _FakePage(
        controls=[
            {"label": "Page 1", "current": True},
            {"label": "Page 2"},
            {"label": "Next"},
        ],
        signatures=[
            {"count": 25, "first": "A", "last": "Z"},
            {"count": 25, "first": "B", "last": "Y"},
        ],
    )

    assert await go_to_next_page(page, _settings(), lambda _m: None) is True
    # The "Next" control (marker p2) was clicked; nothing else was.
    assert page.elements["p2"].clicked is True
    assert page.elements["p0"].clicked is False
    assert page.elements["p1"].clicked is False


async def test_go_to_next_page_uses_the_next_page_number() -> None:
    page = _FakePage(
        controls=[{"label": "Page 1", "current": True}, {"label": "Page 2"}],
        signatures=[
            {"count": 10, "first": "A", "last": "Z"},
            {"count": 10, "first": "C", "last": "X"},
        ],
    )

    assert await go_to_next_page(page, _settings(), lambda _m: None) is True
    assert page.elements["p1"].clicked is True


async def test_go_to_next_page_stops_without_controls() -> None:
    page = _FakePage(controls=[], signatures=[{"count": 0, "first": "", "last": ""}])
    assert await go_to_next_page(page, _settings(), lambda _m: None) is False


async def test_go_to_next_page_stops_on_the_last_page() -> None:
    page = _FakePage(
        controls=[{"label": "Page 4", "current": True}, {"label": "Next", "disabled": True}],
        signatures=[{"count": 8, "first": "A", "last": "Z"}],
    )
    reasons: list[str] = []
    assert (
        await go_to_next_page(page, _settings(), lambda _m: None, reason_out=reasons)
        is False
    )
    assert page.elements["p0"].clicked is False
    assert page.elements["p1"].clicked is False
    assert reasons == []  # the last page is a clean end, not a failure to heal


async def test_go_to_next_page_reports_a_missing_pagination_control() -> None:
    page = _FakePage(controls=[], signatures=[{"count": 0, "first": "", "last": ""}])
    reasons: list[str] = []
    assert (
        await go_to_next_page(page, _settings(), lambda _m: None, reason_out=reasons)
        is False
    )
    assert "pagination controls not found" in reasons[0]
    assert "could not advance" in reasons[0]


def test_pagination_query_discovers_hashed_class_pagination() -> None:
    """The new LinkedIn UI has no stable container class; find by button text."""
    js = linkedin_pagination._PAGINATION_QUERY
    assert "lastPage" in js
    assert "nexts" in js
    assert "aria-current" in js


async def test_go_to_next_page_stops_when_the_list_does_not_change(monkeypatch) -> None:
    monkeypatch.setattr(linkedin_pagination, "_PAGE_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(linkedin_pagination, "_PAGE_POLL_SECONDS", 0.01)
    unchanged = {"count": 10, "first": "A", "last": "Z"}
    page = _FakePage(
        controls=[{"label": "Page 1", "current": True}, {"label": "Next"}],
        signatures=[dict(unchanged), dict(unchanged)],
    )

    assert await go_to_next_page(page, _settings(), lambda _m: None) is False
    assert page.elements["p1"].clicked is True


class _DomClickElement:
    """A control whose CDP click is swallowed but whose DOM click works (BUG-068)."""

    def __init__(self, page: _DomClickPage, marker: str) -> None:
        self.page = page
        self.marker = marker

    async def evaluate(self, js: str, *args):
        if "this.click()" in js:
            self.page.dom_clicks.append(self.marker)
            if self.page.dom_click_advances and self.marker == self.page.next_marker:
                self.page.signature = self.page.after
            return True
        return True

    async def click(self) -> None:
        self.page.cdp_clicks.append(self.marker)


class _DomClickPage:
    """A results page whose CDP mouse click on Next is swallowed by an overlay.

    The page's signature only changes once the next-page control's own DOM
    ``click()`` runs, mirroring the real page where an overlapping element eats the
    coordinate-based CDP mouse event.
    """

    def __init__(self, *, controls, before, after, next_marker="p1", dom_click_advances=True):
        self.controls = controls
        self.signature = before
        self.after = after
        self.next_marker = next_marker
        self.dom_click_advances = dom_click_advances
        self.cdp_clicks: list[str] = []
        self.dom_clicks: list[str] = []
        self.elements: dict[str, _DomClickElement] = {}

    async def evaluate(self, js: str, *args):
        if "data-autojob-page" in js:
            self.elements = {}
            out = []
            for index, control in enumerate(self.controls):
                marker = f"p{index}"
                self.elements[marker] = _DomClickElement(self, marker)
                out.append(
                    {
                        "marker": marker,
                        "label": control["label"],
                        "disabled": control.get("disabled", False),
                        "current": control.get("current", False),
                    }
                )
            return json.dumps({"found": bool(out), "controls": out})
        if "texts" in js:
            return json.dumps(self.signature)
        if "data-autojob-card" in js:
            return json.dumps({"count": 0})
        return ""

    async def get_elements_by_css_selector(self, selector: str) -> list:
        match = re.fullmatch(r'\[data-autojob-page="([^"]+)"\]', selector)
        if match:
            element = self.elements.get(match.group(1))
            return [element] if element is not None else []
        return []


async def test_go_to_next_page_falls_back_to_a_dom_click(monkeypatch) -> None:
    """BUG-068: an overlay swallows the CDP click; the DOM click still advances."""
    monkeypatch.setattr(linkedin_pagination, "_PAGE_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(linkedin_pagination, "_PAGE_POLL_SECONDS", 0.01)
    page = _DomClickPage(
        controls=[{"label": "Page 1", "current": True}, {"label": "Next"}],
        before={"count": 10, "first": "A", "last": "Z"},
        after={"count": 10, "first": "B", "last": "Y"},
    )

    assert await go_to_next_page(page, _settings(), lambda _m: None) is True
    # The CDP click was tried first, then the DOM click advanced the list.
    assert page.cdp_clicks == ["p1"]
    assert page.dom_clicks == ["p1"]


async def test_go_to_next_page_reports_no_change_when_neither_click_moves_it(
    monkeypatch,
) -> None:
    monkeypatch.setattr(linkedin_pagination, "_PAGE_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(linkedin_pagination, "_PAGE_POLL_SECONDS", 0.01)
    unchanged = {"count": 10, "first": "A", "last": "Z"}
    page = _DomClickPage(
        controls=[{"label": "Page 1", "current": True}, {"label": "Next"}],
        before=dict(unchanged),
        after=dict(unchanged),
    )
    reasons: list[str] = []

    assert (
        await go_to_next_page(page, _settings(), lambda _m: None, reason_out=reasons)
        is False
    )
    assert page.cdp_clicks == ["p1"]
    assert page.dom_clicks == ["p1"]  # the DOM retry ran but did not move the list
    assert "did not change after clicking next" in reasons[0]


def test_next_page_url_bumps_start_and_keeps_other_params() -> None:
    url = "https://www.linkedin.com/jobs/search-results/?keywords=python&f_AL=true"
    assert next_page_url(url) == (
        "https://www.linkedin.com/jobs/search-results/"
        "?keywords=python&f_AL=true&start=25"
    )
    assert next_page_url(url + "&start=25").endswith("&start=50")
    assert next_page_url("file:///tmp/jobs.html") == ""
    assert next_page_url("") == ""


class _UrlFallbackPage(_DomClickPage):
    """Both clicks are swallowed; direct URL navigation advances the list."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.url = "https://www.linkedin.com/jobs/search-results/?keywords=python"
        self.navigated = ""

    async def get_url(self) -> str:
        return self.url

    async def goto(self, target: str) -> None:
        self.navigated = target
        self.url = target
        self.signature = self.after


async def test_go_to_next_page_falls_back_to_url_navigation(monkeypatch) -> None:
    """BUG-069: when both clicks are swallowed, load the next results URL."""
    monkeypatch.setattr(linkedin_pagination, "_PAGE_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(linkedin_pagination, "_PAGE_POLL_SECONDS", 0.01)
    page = _UrlFallbackPage(
        controls=[{"label": "Page 1", "current": True}, {"label": "Next"}],
        before={"count": 10, "first": "A", "last": "Z"},
        after={"count": 10, "first": "B", "last": "Y"},
        dom_click_advances=False,
    )

    assert await go_to_next_page(page, _settings(), lambda _m: None) is True
    assert page.cdp_clicks == ["p1"]
    assert page.dom_clicks == ["p1"]
    assert page.navigated.endswith("start=25")
