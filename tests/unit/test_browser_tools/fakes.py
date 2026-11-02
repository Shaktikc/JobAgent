"""Unit tests for the browser-use wrapper (no real browser is launched)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.state import DEFAULT_LOGIN_URL
from src.tools.linkedin import build_jobs_search_url

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
        if "const paneSelectors" in js:
            # Task 2's pane-title query. An empty title keeps the check permissive
            # for these fakes (they do not model the pane heading).
            return json.dumps({"title": ""})
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
        self.stopped = False
        self.screenshot_path: str | None = None

    async def start(self) -> None:
        self.started = True

    async def kill(self) -> None:
        self.killed = True

    async def stop(self) -> None:
        # Releasing the session must never close the browser, so the agent only
        # ever calls stop() (see browser._detach_session).
        self.stopped = True

    async def new_page(self) -> FakePage:
        return self.page

    async def take_screenshot(self, path: str | None = None, full_page: bool = False) -> None:
        Path(path).write_bytes(b"png")
        self.screenshot_path = path

