"""Task 4 regression: the walk must advance through field-less review steps.

LinkedIn's Easy Apply flow inserts profile *review/edit* steps (Resume, Work
experience, ...) that hold **no fillable controls** and whose modal heading is the
constant modal title ("Apply to <company>"). The walk's step fingerprint used to
be built only from that constant title plus the enumerated fields, so two
consecutive review steps looked identical and the walk stopped with
``form did not advance to a new step`` (see ``known Bugs/task_4_bugs.md``,
BUG-032).

These tests are offline: they drive :func:`_task4_on_page` with a tiny fake page
whose per-step payload carries a distinct ``step`` identity (the modal's progress
indicator plus its headings), which is exactly what the fix adds.
"""

from __future__ import annotations

import json
import re

from src.configuration import SessionSettings, Settings
from src.tools import linkedin_easy_apply_fill as fill_tools


class _FakeButton:
    def __init__(self) -> None:
        self.clicked = False

    async def click(self) -> None:
        self.clicked = True


class _FakePage:
    """A minimal page: each ``evaluate`` pops the next form/button payload."""

    def __init__(self, *, enumerations: list[dict], button_batches: list[list[dict]]) -> None:
        self._enumerations = list(enumerations)
        self._button_batches = list(button_batches)
        self.buttons: dict[str, _FakeButton] = {}

    async def evaluate(self, js: str, *args):
        if "data-autojob-fill" in js:
            payload = (
                self._enumerations.pop(0) if self._enumerations else {"open": False, "fields": []}
            )
            return json.dumps(payload)
        if "data-autojob-btn" in js:
            batch = self._button_batches.pop(0) if self._button_batches else []
            return json.dumps({"buttons": batch})
        if "data-autojob-resume" in js:
            return json.dumps({"options": [], "fileInput": False})
        return ""

    async def get_elements_by_css_selector(self, selector: str):
        match = re.search(r'="([^"]+)"', selector)
        if match and match.group(1) in self.buttons:
            return [self.buttons[match.group(1)]]
        return []

    async def get_url(self) -> str:
        return "https://www.linkedin.com/jobs/view/1"


def _settings(tmp_path) -> Settings:
    return Settings(
        session=SessionSettings(headless=True, post_click_wait_seconds=0.0, ask_human=False),
        data_dir=tmp_path / "data",
    )


def test_form_signature_distinguishes_fieldless_steps() -> None:
    """Same constant title + no fields, but a different step → different fingerprint."""
    same_title = "Apply to EVSE"
    assert fill_tools._form_signature(same_title, [], "2/3 pages") != fill_tools._form_signature(
        same_title, [], "3/3 pages"
    )
    # The same step still fingerprints the same (no spurious "advance").
    assert fill_tools._form_signature(same_title, [], "2/3 pages") == fill_tools._form_signature(
        same_title, [], "2/3 pages"
    )


async def test_task4_advances_through_fieldless_review_steps(tmp_path) -> None:
    """Two consecutive review steps (no fields, constant title) must both advance."""
    page = _FakePage(
        enumerations=[
            {"open": True, "title": "Apply to EVSE", "step": "1/3 pages", "fields": []},
            {"open": True, "title": "Apply to EVSE", "step": "2/3 pages", "fields": []},
            {"open": True, "title": "Apply to EVSE", "step": "3/3 pages", "fields": []},
        ],
        button_batches=[
            [{"marker": "b0", "text": "Next", "disabled": False}],
            [{"marker": "b0", "text": "Next", "disabled": False}],
            [{"marker": "b0", "text": "Submit application", "disabled": False}],
        ],
    )
    page.buttons = {"b0": _FakeButton()}

    outcome = await fill_tools._task4_on_page(
        page, None, None, {}, _settings(tmp_path), lambda _m: None
    )

    assert outcome.steps_advanced == 2
    assert outcome.reached_terminal_step is True
    assert outcome.submitted is False
    assert "form did not advance" not in outcome.notes
    assert page.buttons["b0"].clicked is True
