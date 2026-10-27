"""Unit tests for Task 13's Date posted filter (no real browser).

Covers the pure label/range/URL helpers and the deterministic UI path
(pill -> **Past 24 hours** -> **Show results**) with fake elements, including
the option-absent and page-stays-unfiltered failure cases.
"""

from __future__ import annotations

import json
import re

import pytest

from src.configuration import SessionSettings, Settings
from src.tools import linkedin_date_posted as date_posted
from src.tools.linkedin_search import easy_apply_filter as easy_apply


class FakeElement:
    def __init__(self, label: str, *, on_click=None, checked: bool = False) -> None:
        self.label = label
        self.on_click = on_click
        self.checked = checked
        self.clicked = 0
        self.scrolled = False
        self.attributes = {"aria-label": label}

    async def get_attribute(self, name: str) -> str | None:
        return self.attributes.get(name)

    async def evaluate(self, js: str, *args):
        if "scrollIntoView" in js:
            self.scrolled = True
            return self.label
        if "this.click()" in js:
            self.clicked += 1
            if self.on_click is not None:
                self.on_click()
            return True
        return self.label

    async def click(self) -> None:
        self.clicked += 1
        if self.on_click is not None:
            self.on_click()


class FakePage:
    def __init__(self) -> None:
        self.current_url = "https://www.linkedin.com/jobs/search/?keywords=software+engineer"
        self.goto_calls: list[str] = []
        self.ignore_goto = False
        self.options_visible = False
        self.pill: FakeElement | None = None
        self.options: list[FakeElement] = []
        self.show_results: FakeElement | None = None
        self.control_elements: dict[str, FakeElement] = {}
        self.option_elements: dict[str, FakeElement] = {}

    def add_pill(self, on_click=None) -> FakeElement:
        pill = FakeElement("Date posted filter.", on_click=on_click)
        self.pill = pill
        return pill

    def add_option(self, label: str, on_click=None, checked: bool = False) -> FakeElement:
        option = FakeElement(label, on_click=on_click, checked=checked)
        self.options.append(option)
        return option

    async def get_url(self) -> str:
        return self.current_url

    async def get_title(self) -> str:
        return "Jobs"

    async def goto(self, url: str) -> None:
        self.goto_calls.append(url)
        if not self.ignore_goto:
            self.current_url = url

    async def evaluate(self, js: str, *args):
        if "readyState" in js:
            return "complete"
        if "f_AL=true" in js and "location.search" in js:
            return json.dumps({"selected": "f_AL=true" in self.current_url})
        if "data-autojob-date-option" in js:
            self.option_elements = {}
            entries = []
            for index, option in enumerate(self.options if self.options_visible else []):
                marker = f"o{index}"
                self.option_elements[marker] = option
                entries.append(
                    {
                        "marker": marker,
                        "label": option.label,
                        "checked": option.checked,
                        "value": "",
                    }
                )
            return json.dumps({"options": entries})
        if "data-autojob-date-apply" in js:
            marker = "apply" if self.show_results is not None and self.options_visible else None
            return json.dumps({"marker": marker})
        if "data-autojob-date" in js:
            self.control_elements = {}
            entries = []
            controls = [self.pill] if self.pill is not None else []
            for index, control in enumerate(controls):
                marker = f"d{index}"
                self.control_elements[marker] = control
                entries.append(
                    {
                        "marker": marker,
                        "label": control.label,
                        "checked": control.checked,
                    }
                )
            return json.dumps({"controls": entries})
        return ""

    async def get_elements_by_css_selector(self, selector: str) -> list:
        for attribute, registry in (
            ("data-autojob-date-option", self.option_elements),
            ("data-autojob-date-apply", {"apply": self.show_results}),
            ("data-autojob-date", self.control_elements),
        ):
            match = re.fullmatch(rf'\[{attribute}="([^"]+)"\]', selector)
            if match:
                element = registry.get(match.group(1))
                return [element] if element is not None else []
        return []


def _settings(tmp_path) -> Settings:
    return Settings(
        session=SessionSettings(post_click_wait_seconds=0, ai_search_timeout_seconds=0),
        data_dir=tmp_path,
    )


def test_normalize_label_collapses_whitespace_and_period() -> None:
    assert date_posted.normalize_label("  Past   24 HOURS. ") == "past 24 hours"
    assert date_posted.normalize_label(None) == ""


def test_date_posted_filter_labels() -> None:
    assert date_posted.looks_like_date_posted_filter("Date posted")
    assert date_posted.looks_like_date_posted_filter("Date posted filter.")
    assert date_posted.looks_like_date_posted_filter("Past 24 hours")
    assert date_posted.looks_like_date_posted_filter("Past week")
    # A job card's age text must never be mistaken for the filter.
    assert not date_posted.looks_like_date_posted_filter("Posted 1 day ago")
    assert not date_posted.looks_like_date_posted_filter("Easy Apply filter.")
    assert not date_posted.looks_like_date_posted_filter("Date")


def test_date_range_helpers() -> None:
    assert date_posted.looks_like_past_24_hours("  Past   24 hours ")
    assert not date_posted.looks_like_past_24_hours("Past week")
    assert date_posted.date_range_seconds("Past 24 hours") == 86400
    assert date_posted.date_range_seconds("Past week") == 604800
    assert date_posted.date_range_seconds("Past month") == 2592000
    assert date_posted.date_range_seconds("Date posted") is None
    assert date_posted.pick_past_24_hours_index(["Past month", "Past 24 hours"]) == 1
    assert date_posted.pick_date_posted_filter_index(["Easy Apply", "Date posted"]) == 1


def test_url_helpers_preserve_existing_parameters() -> None:
    url = "https://www.linkedin.com/jobs/search/?keywords=software+engineer&f_AL=true"
    filtered = date_posted.with_past_24_hours(url)
    assert "keywords=software+engineer" in filtered
    assert "f_AL=true" in filtered
    assert "f_TPR=r86400" in filtered
    assert date_posted.url_has_past_24_hours(filtered)
    # An existing range is replaced, not duplicated.
    replaced = date_posted.with_past_24_hours(filtered.replace("r86400", "r604800"))
    assert "r604800" not in replaced
    assert replaced.count("f_TPR=") == 1
    assert date_posted.url_has_past_24_hours(replaced)


def test_url_helpers_reject_invalid_urls() -> None:
    assert date_posted.with_past_24_hours("") == ""
    assert date_posted.with_past_24_hours("not-a-url") == ""
    assert date_posted.url_has_past_24_hours("") is False
    assert (
        date_posted.url_has_past_24_hours("https://www.linkedin.com/jobs/?f_TPR=r604800")
        is False
    )


async def test_select_past_24_hours_uses_the_visible_ui(tmp_path) -> None:
    page = FakePage()
    pill = page.add_pill()

    def _open() -> None:
        page.options_visible = True

    pill.on_click = _open
    option = page.add_option("Past 24 hours")

    def _select() -> None:
        option.checked = True

    option.on_click = _select
    show = FakeElement("Show results")

    def _apply() -> None:
        page.current_url = date_posted.with_past_24_hours(page.current_url)

    show.on_click = _apply
    page.show_results = show

    selected, note = await date_posted.select_past_24_hours(page, _settings(tmp_path))

    assert selected is True
    assert note == ""
    assert pill.clicked == 1
    assert option.clicked == 1
    assert show.clicked == 1
    assert page.current_url.endswith("f_TPR=r86400") or "f_TPR=r86400" in page.current_url
    assert pill.scrolled and option.scrolled and show.scrolled


async def test_select_past_24_hours_falls_back_to_url_when_option_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(date_posted, "_DATE_OPTION_TIMEOUT_SECONDS", 0)
    page = FakePage()
    page.add_pill()
    # The popover never shows any option, so the visible path cannot complete.
    page.options_visible = False

    selected, note = await date_posted.select_past_24_hours(page, _settings(tmp_path))

    assert selected is True
    assert "URL fallback" in note
    assert any("f_TPR=r86400" in url for url in page.goto_calls)


async def test_select_past_24_hours_fails_when_page_stays_unfiltered(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(date_posted, "_DATE_OPTION_TIMEOUT_SECONDS", 0)
    page = FakePage()
    page.ignore_goto = True  # the fallback URL loads but the filter is not applied

    selected, note = await date_posted.select_past_24_hours(page, _settings(tmp_path))

    assert selected is False
    assert "could not be verified" in note
    assert page.goto_calls  # the fallback was attempted


async def test_select_past_24_hours_skips_when_url_already_filtered(tmp_path) -> None:
    page = FakePage()
    page.current_url = date_posted.with_past_24_hours(page.current_url)
    page.add_pill()

    selected, note = await date_posted.select_past_24_hours(page, _settings(tmp_path))

    assert selected is True
    assert note == ""
    assert page.pill.clicked == 0
    assert page.goto_calls == []


async def test_date_posted_filter_selected_from_checked_option(tmp_path) -> None:
    page = FakePage()
    page.options_visible = True
    page.add_option("Past week", checked=False)
    page.add_option("Past 24 hours", checked=True)

    assert await date_posted.date_posted_filter_selected(page) is True


async def test_date_posted_filter_applied_requires_the_url_param(tmp_path) -> None:
    page = FakePage()
    page.options_visible = True
    page.add_option("Past 24 hours", checked=True)

    # A checked option alone is not enough: the popover may not be applied.
    assert await date_posted.date_posted_filter_selected(page) is True
    assert await date_posted.date_posted_filter_applied(page) is False

    page.current_url = date_posted.with_past_24_hours(page.current_url)
    assert await date_posted.date_posted_filter_applied(page) is True


async def test_checked_option_without_url_falls_back_to_filtered_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A checked radio must not pass unless the results URL is filtered."""
    monkeypatch.setattr(date_posted, "_DATE_OPTION_TIMEOUT_SECONDS", 0)
    page = FakePage()
    page.add_pill(on_click=lambda: setattr(page, "options_visible", True))
    page.add_option("Past 24 hours", checked=True)

    selected, note = await date_posted.select_past_24_hours(page, _settings(tmp_path))

    assert selected is True
    assert "URL fallback" in note
    assert date_posted.url_has_past_24_hours(page.current_url)


async def test_easy_apply_url_reselection_keeps_the_date_range(tmp_path) -> None:
    page = FakePage()
    page.current_url = date_posted.with_past_24_hours(page.current_url)

    selected, note = await easy_apply.select_easy_apply_filter(
        page, _settings(tmp_path), prefer_url=True
    )

    assert selected is True
    assert note == ""
    assert "f_AL=true" in page.current_url
    assert "f_TPR=r86400" in page.current_url
    # The pill was not clicked; the filter was applied through the URL.
    assert page.pill is None


async def test_date_posted_filter_selected_false_when_option_unchecked(tmp_path) -> None:
    page = FakePage()
    page.options_visible = True
    page.add_option("Past 24 hours", checked=False)

    assert await date_posted.date_posted_filter_selected(page) is False


async def test_find_show_results_button_and_date_filter(tmp_path) -> None:
    page = FakePage()
    pill = page.add_pill()
    page.show_results = FakeElement("Show results")
    page.options_visible = True

    found_pill = await date_posted.find_date_posted_filter(page)
    found_show = await date_posted.find_show_results_button(page)

    assert found_pill is pill
    assert found_show is page.show_results
