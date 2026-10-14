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
    assert await go_to_next_page(page, _settings(), lambda _m: None) is False
    assert page.elements["p0"].clicked is False
    assert page.elements["p1"].clicked is False


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
