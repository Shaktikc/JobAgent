"""Task 4 regression: the walk must advance through field-less review steps.

LinkedIn's Easy Apply flow inserts profile *review/edit* steps (Resume, Work
experience, ...) that hold **no fillable controls** and whose modal heading is the
constant modal title ("Apply to <company>"). The walk's step fingerprint used to
be built only from that constant title plus the enumerated fields, so two
consecutive review steps looked identical and the walk stopped with
``form did not advance to a new step`` (see ``known Bugs/task_4_bugs.md``,
BUG-032).

These tests are offline: they drive :func:`_task4_on_page` with a tiny in-memory
form whose per-step payload carries a distinct ``step`` identity (the modal's
progress indicator, headings, and a hash of its whole visible text), which is
exactly what the fix adds.
"""

from __future__ import annotations

import json
import re

from src.configuration import SessionSettings, Settings
from src.tools import linkedin_easy_apply_fill as fill_tools


class _FakeButton:
    def __init__(self, on_click=None) -> None:
        self.clicked = False
        self._on_click = on_click

    async def click(self) -> None:
        self.clicked = True
        if self._on_click is not None:
            self._on_click()


class _FakeForm:
    """A tiny in-memory Easy Apply form: ``steps`` is one payload per step and
    clicking Next advances to the next step."""

    def __init__(self, steps, buttons_per_step) -> None:
        self._steps = list(steps)
        self._buttons = list(buttons_per_step)
        self.index = 0
        self.buttons: dict[str, _FakeButton] = {}

    def _clamp(self, seq):
        return seq[min(self.index, len(seq) - 1)]

    def _advance(self) -> None:
        self.index += 1

    async def evaluate(self, js: str, *args):
        if "data-autojob-fill" in js:
            return json.dumps(self._clamp(self._steps))
        if "data-autojob-btn" in js:
            return json.dumps({"buttons": self._clamp(self._buttons)})
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


def _make_form(steps, buttons_per_step) -> _FakeForm:
    form = _FakeForm(steps, buttons_per_step)
    form.buttons = {"b0": _FakeButton(form._advance)}
    return form


class _SlowRenderForm(_FakeForm):
    """A form whose next step renders only after a few reads (LinkedIn can lag)."""

    def __init__(self, steps, buttons_per_step, *, delay_reads: int) -> None:
        super().__init__(steps, buttons_per_step)
        self.delay_reads = delay_reads
        self.pending_reads = 0

    def _advance(self) -> None:
        self.pending_reads = self.delay_reads

    async def evaluate(self, js: str, *args):
        if "data-autojob-fill" in js and self.pending_reads:
            self.pending_reads -= 1
            if self.pending_reads == 0:
                self.index += 1
        return await super().evaluate(js, *args)


def _settings(tmp_path, **session) -> Settings:
    session.setdefault("headless", True)
    session.setdefault("post_click_wait_seconds", 0.0)
    session.setdefault("ask_human", False)
    return Settings(session=SessionSettings(**session), data_dir=tmp_path / "data")


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
    form = _make_form(
        steps=[
            {"open": True, "title": "Apply to EVSE", "step": "1/3 pages · text:1", "fields": []},
            {"open": True, "title": "Apply to EVSE", "step": "2/3 pages · text:2", "fields": []},
            {"open": True, "title": "Apply to EVSE", "step": "3/3 pages · text:3", "fields": []},
        ],
        buttons_per_step=[
            [{"marker": "b0", "text": "Next", "disabled": False}],
            [{"marker": "b0", "text": "Next", "disabled": False}],
            [{"marker": "b0", "text": "Submit application", "disabled": False}],
        ],
    )

    outcome = await fill_tools._task4_on_page(
        form, None, None, {}, _settings(tmp_path), lambda _m: None
    )

    assert outcome.steps_advanced == 2
    assert outcome.reached_terminal_step is True
    assert outcome.submitted is False
    assert "form did not advance" not in outcome.notes
    assert form.buttons["b0"].clicked is True


class _OneMissForm(_FakeForm):
    """A form whose first Next click is swallowed; the retry must advance it."""

    def __init__(self, steps, buttons_per_step) -> None:
        super().__init__(steps, buttons_per_step)
        self.clicks = 0

    def _advance(self) -> None:
        self.clicks += 1
        if self.clicks > 1:
            self.index += 1


async def test_task4_retries_a_swallowed_next_click_once(tmp_path) -> None:
    """One missed Next click must be retried with a fresh handle (BUG-048)."""
    form = _OneMissForm(
        steps=[
            {"open": True, "title": "Apply to Acme", "step": "1/2 pages", "fields": []},
            {"open": True, "title": "Apply to Acme", "step": "2/2 pages", "fields": []},
        ],
        buttons_per_step=[
            [{"marker": "b0", "text": "Next", "disabled": False}],
            [{"marker": "b0", "text": "Submit application", "disabled": False}],
        ],
    )
    form.buttons = {"b0": _FakeButton(form._advance)}

    outcome = await fill_tools._task4_on_page(
        form,
        None,
        None,
        {},
        _settings(tmp_path, easy_apply_timeout_seconds=0.1),
        lambda _m: None,
    )

    assert form.clicks == 2
    assert outcome.steps_advanced == 1
    assert outcome.reached_terminal_step is True
    assert "form did not advance" not in outcome.notes


async def test_task4_waits_for_a_slow_review_step_to_render(tmp_path) -> None:
    """Review is clicked, the next step renders a moment later — do not stop early."""
    def step(identity: str) -> dict:
        return {
            "open": True,
            "title": "Apply to SwipeJobs",
            "step": identity,
            "fields": [],
        }

    form = _SlowRenderForm(
        steps=[step("1/2 pages · text:1"), step("2/2 pages · text:2")],
        buttons_per_step=[
            [{"marker": "b0", "text": "Review", "disabled": False}],
            [{"marker": "b0", "text": "Submit application", "disabled": False}],
        ],
        delay_reads=2,
    )
    form.buttons = {"b0": _FakeButton(form._advance)}

    outcome = await fill_tools._task4_on_page(
        form,
        None,
        None,
        {},
        _settings(tmp_path, easy_apply_timeout_seconds=0.2),
        lambda _m: None,
    )

    assert outcome.steps_advanced == 1
    assert outcome.reached_terminal_step is True
    assert outcome.submitted is False
    assert "form did not advance" not in outcome.notes
