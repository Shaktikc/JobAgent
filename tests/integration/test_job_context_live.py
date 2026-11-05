"""Opt-in live-browser test for Task 12's job-context answers.

It serves a self-contained Easy Apply fixture with two required textareas:

1. **"What attracts you to Propeller as an employer?"** — a job-specific question
   the context-aware chooser answers from the job description and resume.
2. **"What is your expected salary?"** — a normal question with no context answer;
   it must still be left for Task 5 (the human).

The test drives the **real** Task 4 fill path in a real Chromium window, with a
fake LLM reply and a fake Task 5 prompt, so it proves the routing, validation,
DOM fill, FormField provenance, and Task 9 status line together.

Enable it (the ``browser`` extra must be installed)::

    uv sync --extra browser
    uvx playwright install chromium
    $env:AUTOJOB_JOB_CONTEXT_LIVE="1"
    uv run pytest tests/integration/test_job_context_live.py -s

Skipped by default so the unit suite stays offline.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.configuration import LLMSettings, SessionSettings, Settings
from src.state import JobAnswerContext, JobDescription, Task5Outcome
from src.tools import browser as browser_tools
from src.tools.job_context_answers import ContextAwareAnswerChooser
from src.tools.llm_answers import QuestionDecision

pytest.importorskip("browser_use")

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("AUTOJOB_JOB_CONTEXT_LIVE"),
        reason="set AUTOJOB_JOB_CONTEXT_LIVE=1 to run the live Task 12 browser test",
    ),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

_QUESTION = "What attracts you to Propeller as an employer?*"
_ANSWER = "I am drawn to Propeller's mission to make hiring fair for everyone."
_EVIDENCE = "Propeller's mission is to make hiring fair for everyone."

_FORM = """<!doctype html>
<html><head><meta charset="utf-8"><title>Easy Apply</title></head><body>
<div class="jobs-easy-apply-modal" role="dialog">
  <h3>Apply to Propeller</h3>
  <div class="jobs-easy-apply-form-element">
    <label for="q1">__QUESTION__</label>
    <textarea id="q1" name="q1" required></textarea>
  </div>
  <div class="jobs-easy-apply-form-element">
    <label for="q2">What is your expected salary?*</label>
    <textarea id="q2" name="q2" required></textarea>
  </div>
  <footer class="artdeco-modal__actionbar">
    <button id="submit" aria-label="Submit application">Submit application</button>
  </footer>
</div>
<script>
  window.__submitted = false;
  document.getElementById('submit').addEventListener('click', function () {
    window.__submitted = true;
  });
</script>
</body></html>
"""
_FORM = _FORM.replace("__QUESTION__", _QUESTION)

_READ_STATE_JS = """() => JSON.stringify({
  q1: document.getElementById('q1').value,
  q2: document.getElementById('q2').value,
  submitted: window.__submitted === true
})"""


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        session=SessionSettings(
            headless=True,
            post_click_wait_seconds=0.0,
            ask_human=True,
            ask_timeout_seconds=5.0,
            ask_poll_seconds=0.1,
            easy_apply_timeout_seconds=10.0,
        ),
        # A throwaway profile keeps the developer's real run untouched.
        data_dir=tmp_path / "data",
    )


def _context() -> JobAnswerContext:
    return JobAnswerContext(
        job_description=JobDescription(
            title="Senior Python Engineer",
            company="Propeller",
            location="Sydney",
            body=_EVIDENCE + " We build Python services.",
        ),
        resume_path="resumes/context.txt",
        resume_text="Python engineer with 6 years building reliable services.",
        resume_profile={"summary": "Python engineer", "skills": ["Python"]},
    )


class _FakeClient:
    """Return a grounded answer only for the job-specific question."""

    def __init__(self) -> None:
        self.chat = self
        self.completions = self

    async def create(self, **kwargs):
        prompt = kwargs["messages"][-1]["content"]
        if "attracts you" in prompt:
            body = json.dumps(
                {
                    "job_specific": True,
                    "answer": _ANSWER,
                    "sources": ["job_description"],
                    "evidence": [_EVIDENCE],
                    "rationale": "company mission",
                }
            )
        else:
            body = json.dumps(
                {
                    "job_specific": False,
                    "answer": "",
                    "sources": [],
                    "evidence": [],
                    "rationale": "not about this job",
                }
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=body))
            ]
        )


class _RecordingStatus:
    def __init__(self) -> None:
        self.llm_lines: list[str] = []

    def llm(self, action: str, detail: str = "") -> None:
        self.llm_lines.append(f"LLM: {action}" + (f" - {detail}" if detail else ""))

    def step(self, message: str) -> None:
        pass

    def __call__(self, message: str) -> None:
        pass


async def _unknown_store(question: str, field_type: str, options: list[str]) -> QuestionDecision:
    return QuestionDecision(question=question)


async def test_job_context_answers_a_job_question_and_leaves_salary_to_task5(
    tmp_path: Path, monkeypatch
) -> None:
    from src.tools.linkedin_easy_apply_fill import form_walk

    settings = _settings(tmp_path)
    page_file = tmp_path / "easy_apply.html"
    page_file.write_text(_FORM, encoding="utf-8")

    chooser = ContextAwareAnswerChooser(
        _context(), LLMSettings(api_key="k", model="m"), {}, _unknown_store
    )
    chooser._context_chooser._client = _FakeClient()
    asked: list[str] = []

    async def fake_ask(page, question, field_type, hint, settings, notify, human, **kwargs):
        asked.append(question)
        return None

    monkeypatch.setattr(form_walk.core, "ask_human_for_answer", fake_ask)

    browser = browser_tools.build_browser(settings)
    await browser.start()
    page = await browser.new_page()
    status = _RecordingStatus()
    try:
        await page.goto(page_file.as_uri())
        await browser_tools._wait_for_load(page, 10)
        outcome = await browser_tools._task4_on_page(
            page,
            browser,
            None,
            {},
            settings,
            status,
            human=Task5Outcome(),
            chooser=chooser,
            context=_context(),
        )
        state = json.loads(await page.evaluate(_READ_STATE_JS))
    finally:
        await browser.kill()

    assert state["q1"] == _ANSWER
    assert state["q2"] == ""
    assert state["submitted"] is False
    assert asked == ["What is your expected salary?*"]

    records = {record.question: record for record in outcome.fields}
    job_record = records[_QUESTION]
    assert job_record.answer_source == "job_description"
    assert job_record.job_specific is True
    assert job_record.context_evidence == [_EVIDENCE]
    assert "What is your expected salary?*" in outcome.unknown_fields
    assert any(
        "from the job description" in line and "Propeller" in line
        for line in status.llm_lines
    )
    assert outcome.reached_terminal_step is True
    assert outcome.submitted is False
