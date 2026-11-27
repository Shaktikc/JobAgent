"""LinkedIn's "Job search safety reminder" is closed and the job is skipped."""

from __future__ import annotations

import json

from src.configuration import SessionSettings, Settings
from src.graph import _route_after_open_form
from src.state import Task2Outcome
from src.tools import linkedin_safety_reminder as reminder
from src.tools.linkedin_easy_apply_open import open_easy_apply_form

_SAFETY_MARK = "job search safety reminder"
_MODAL_JS = "jobs-easy-apply-modal"


class _Button:
    def __init__(self, page) -> None:
        self.page = page
        self.clicks = 0

    async def get_attribute(self, name: str):
        return "Easy Apply to this job" if name == "aria-label" else None

    async def evaluate(self, js: str, *args) -> str:
        return "BUTTON" if "tagName" in js else "Easy Apply to this job"

    async def click(self) -> None:
        self.clicks += 1
        self.page.reminder_open = True  # the reminder appears instead of the form


class _Page:
    def __init__(self, *, has_dismiss: bool = True) -> None:
        self.reminder_open = False
        self.has_dismiss = has_dismiss
        self.escapes = 0
        self.button = _Button(self)

    async def evaluate(self, js: str, *args):
        if _SAFETY_MARK in js:
            if not self.reminder_open:
                return json.dumps({"found": False, "clicked": False})
            if args and args[0] == "close" and self.has_dismiss:
                self.reminder_open = False
                return json.dumps({"found": True, "clicked": True})
            return json.dumps({"found": True, "clicked": False})
        if _MODAL_JS in js:
            return json.dumps({"open": False, "text": ""})
        return ""

    async def press(self, key: str) -> None:
        if key == "Escape":
            self.escapes += 1
            self.reminder_open = False

    async def get_elements_by_css_selector(self, selector: str) -> list:
        return [self.button] if selector == "button.jobs-apply-button" else []

    async def get_url(self) -> str:
        return "https://www.linkedin.com/jobs/search-results/"

    async def get_title(self) -> str:
        return "Jobs"


def _settings(tmp_path) -> Settings:
    return Settings(
        session=SessionSettings(
            headless=True,
            post_click_wait_seconds=0.0,
            easy_apply_timeout_seconds=0.05,
            pane_switch_timeout_seconds=0.05,
        ),
        data_dir=tmp_path / "data",
    )


async def test_open_closes_the_safety_reminder_and_skips(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(reminder, "_CLOSE_POLL_SECONDS", 0.0)
    page = _Page()
    outcome = Task2Outcome(job_title="AI Engineer", job_selected=True)

    opened, outcome = await open_easy_apply_form(page, _settings(tmp_path), None, outcome)

    assert opened is False
    assert page.button.clicks == 1
    assert page.reminder_open is False
    assert outcome.safety_reminder_skipped is True
    assert outcome.application_form_opened is False
    assert "safety reminder" in outcome.notes


async def test_close_falls_back_to_escape(monkeypatch) -> None:
    monkeypatch.setattr(reminder, "_CLOSE_POLL_SECONDS", 0.0)
    page = _Page(has_dismiss=False)
    page.reminder_open = True

    assert await reminder.close_safety_reminder(page) is True
    assert page.escapes == 1


def test_route_after_open_form_skips_to_next_job() -> None:
    assert _route_after_open_form({"status": "skipped"}) == "next_job"
    assert _route_after_open_form({"status": "form_open"}) == "fill"
