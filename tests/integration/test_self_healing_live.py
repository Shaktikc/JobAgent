"""Opt-in live-browser tests for Task 11 and its recorded bug (BUG-048).

1. The two-version Easy Apply fixture: the first version has no resume control, so
   the real Task 4 walk fails. The self-healing loop must capture the failure,
   close the real Chromium session, open a fresh session on the second fixture,
   attach the resume, and stop before Submit.

2. BUG-048 regression: Task 9's status panel is a top-layer popover. It used to
   cover the Easy Apply footer's **Next** button and swallow the click, leaving the
   form stuck on step 1 ("form did not advance"). With ``pointer-events:none`` the
   panel never intercepts the click, so the walk advances.

Enable it (the ``browser`` extra must be installed)::

    $env:AUTOJOB_SELF_HEAL_LIVE="1"
    uv run pytest tests/integration/test_self_healing_live.py -s
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from src.configuration import SelfHealingSettings, SessionSettings, Settings
from src.state import AgentOutcome, JobDescription, Task1Outcome, Task2Outcome, Task5Outcome
from src.tools import browser as browser_tools
from src.tools.llm_answers import QuestionDecision
from src.tools.self_healing.loop import failure_reason, heal_fill_failure
from src.tools.self_healing.models import JobTarget
from src.tools.self_healing.recovery import (
    ReopenResult,
    close_run_force,
    reopen_same_job,
)

pytest.importorskip("browser_use")

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("AUTOJOB_SELF_HEAL_LIVE"),
        reason="set AUTOJOB_SELF_HEAL_LIVE=1 to run the live self-healing test",
    ),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

_RESUME_NAME = "Self_Heal_Resume.txt"

_FORM = """<!doctype html>
<html><head><meta charset="utf-8"><title>Easy Apply</title></head><body>
<div class="artdeco-modal jobs-easy-apply-modal" role="dialog">
  <div class="artdeco-modal__content">
    <section data-step="1">__RESUME__</section>
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

_RESUME_CONTROL = """
<fieldset class="jobs-easy-apply-form-element">
  <legend>Select a resume</legend>
  <label for="resume-listed">__RESUME_NAME__</label>
  <input id="resume-listed" name="resume" type="radio" value="listed">
</fieldset>
"""

_READ_STATE_JS = """() => JSON.stringify({
  submitted: window.__submitted === true,
  resume_checked: !!document.getElementById('resume-listed')?.checked
})"""

_JOB_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Backend Engineer | LinkedIn</title></head><body>
<div class="job-details-jobs-unified-top-card__job-title">Backend Engineer</div>
<div class="job-details-jobs-unified-top-card__company-name">Acme</div>
<button class="jobs-apply-button" data-live-test-job-apply-button>Easy Apply</button>
<div id="modal" class="artdeco-modal jobs-easy-apply-modal" role="dialog" style="display:none">
  <h2>Apply to Acme</h2>
  <fieldset class="jobs-easy-apply-form-element">
    <legend>Select a resume</legend>
    <label for="resume-listed">__RESUME_NAME__</label>
    <input id="resume-listed" name="resume" type="radio" value="listed">
  </fieldset>
  <footer class="artdeco-modal__actionbar">
    <button aria-label="Submit application">Submit application</button>
  </footer>
</div>
<script>
  window.__submitted = false;
  document.querySelector('.jobs-apply-button').addEventListener('click', function () {
    document.getElementById('modal').style.display = 'block';
  });
  document.querySelector('button[aria-label="Submit application"]').addEventListener(
    'click', function () { window.__submitted = true; }
  );
</script>
</body></html>
"""


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        session=SessionSettings(
            headless=True,
            step_delay_seconds=0,
            post_click_wait_seconds=0,
            ask_human=False,
            easy_apply_timeout_seconds=10,
            keep_open_timeout_seconds=1,
        ),
        self_healing=SelfHealingSettings(
            enabled=True,
            max_repair_attempts=2,
            close_timeout_seconds=30,
        ),
        data_dir=tmp_path / "data",
    )


def _write_fixture(tmp_path: Path, name: str, resume_control: bool) -> Path:
    html = _FORM.replace(
        "__RESUME__",
        _RESUME_CONTROL.replace("__RESUME_NAME__", _RESUME_NAME) if resume_control else "",
    )
    path = tmp_path / name
    path.write_text(html, encoding="utf-8")
    return path


async def _start_browser(settings: Settings, page_path: Path):
    browser = browser_tools.build_browser(settings)
    await browser.start()
    page = await browser.new_page()
    await page.goto(page_path.as_uri())
    await browser_tools._wait_for_load(page, 10)
    run_id = uuid4().hex
    browser_tools._ACTIVE_RUNS[run_id] = browser_tools._Run(session=browser, page=page)
    return run_id


async def _no_answer(question: str, field_type: str, options: list[str]) -> QuestionDecision:
    return QuestionDecision(question=question)


def _reader(settings: Settings, answers: dict):
    async def fill_fn(run_id, resume_path, settings=None, progress=None):
        from src.tools.linkedin_easy_apply_fill import _task4_on_page

        run = browser_tools.get_run(run_id)
        assert run is not None
        outcome = await _task4_on_page(
            run.page,
            run.session,
            resume_path,
            answers,
            settings or _settings(Path.cwd()),
            progress or (lambda _message: None),
            chooser=_no_answer,
        )
        return outcome, Task5Outcome(enabled=False)

    return fill_fn


async def test_reopen_same_job_opens_the_recorded_url(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    job_page = tmp_path / "job.html"
    job_page.write_text(_JOB_PAGE.replace("__RESUME_NAME__", _RESUME_NAME), encoding="utf-8")
    sessions = []

    async def fake_start_tasks(url, query, settings=None, progress=None):
        browser = browser_tools.build_browser(settings)
        await browser.start()
        page = await browser.new_page()
        await page.goto((tmp_path / "results.html").as_uri())
        await browser_tools._wait_for_load(page, 10)
        run_id = uuid4().hex
        browser_tools._ACTIVE_RUNS[run_id] = browser_tools._Run(session=browser, page=page)
        sessions.append(browser)
        return AgentOutcome(
            task1=Task1Outcome(logged_in=True, results_found=True, easy_apply_filter_selected=True),
            task2=Task2Outcome(),
        ), run_id

    (tmp_path / "results.html").write_text("<html><body>results</body></html>", encoding="utf-8")
    monkeypatch.setattr(browser_tools, "start_tasks", fake_start_tasks)
    result = await reopen_same_job(
        JobTarget(
            title="Backend Engineer",
            company="Acme",
            url=job_page.as_uri(),
            search_query="backend",
        ),
        settings,
    )
    try:
        assert result.opened is True
        assert result.task2 is not None
        assert result.task2.application_form_opened is True
        assert result.description is not None
        assert result.description.title == "Backend Engineer"
        run = browser_tools.get_run(result.run_id)
        assert run is not None
        observed = json.loads(await run.page.evaluate(_READ_STATE_JS))
        assert observed["submitted"] is False
    finally:
        await close_run_force(result.run_id, settings)


async def test_self_healing_closes_and_reopens_the_same_job(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    resume = tmp_path / "resumes" / _RESUME_NAME
    resume.parent.mkdir(parents=True)
    resume.write_text("Senior Python engineer", encoding="utf-8")

    first_page = _write_fixture(tmp_path, "first.html", resume_control=False)
    second_page = _write_fixture(tmp_path, "second.html", resume_control=True)
    first_run = await _start_browser(settings, first_page)
    fill_fn = _reader(settings, {})
    result = None
    try:
        failed, _ = await fill_fn(first_run, str(resume), settings, lambda _message: None)
        assert failure_reason(failed)

        async def reopen_fn(target, reopen_settings, notify):
            second_run = await _start_browser(reopen_settings, second_page)
            return ReopenResult(
                run_id=second_run,
                task2=Task2Outcome(
                    job_title="Backend Engineer", application_form_opened=True
                ),
                description=JobDescription(
                    title="Backend Engineer",
                    company="Acme",
                    page_url="https://www.linkedin.com/jobs/view/1",
                ),
            )

        result = await heal_fill_failure(
            run_id=first_run,
            task4=failed,
            task5=Task5Outcome(enabled=False),
            settings=settings,
            target=JobTarget(
                title="Backend Engineer",
                company="Acme",
                url="https://www.linkedin.com/jobs/view/1",
            ),
            resume_path=str(resume),
            fill_fn=fill_fn,
            reopen_fn=reopen_fn,
            bug_root=tmp_path,
        )

        assert result.recovered is True
        assert result.outcome.attempts == 1
        assert result.task4 is not None
        assert result.task4.resume_attached is True
        assert result.task4.submitted is False
        assert browser_tools.get_run(first_run) is None

        new_run = browser_tools.get_run(result.run_id)
        assert new_run is not None
        observed = json.loads(await new_run.page.evaluate(_READ_STATE_JS))
        assert observed == {"submitted": False, "resume_checked": True}
        assert (Path(result.outcome.last_bundle) / "screenshot.png").is_file()
        record = tmp_path / "known Bugs" / "self_healing_bugs.md"
        assert record.is_file()
        record_text = record.read_text(encoding="utf-8")
        assert "BUG-001" in record_text
        assert "🟢 Fixed" in record_text
    finally:
        if result is not None:
            await close_run_force(result.run_id, settings)
        await close_run_force(first_run, settings)


# BUG-048: the Task 9 status panel is a top-layer popover with the maximum
# z-index. Without ``pointer-events:none`` it covers the Easy Apply footer's Next
# button and the CDP click lands on the panel, so the step never advances. The
# Next button here is pinned to the panel's own corner (bottom-left) to reproduce
# the overlap.
_OVERLAY_FORM_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Easy Apply</title></head><body>
<div id="root">
  <h2>Apply to Acme</h2>
  <label for="email">Email address*</label>
  <select id="email" name="email">
    <option value="me@example.com" selected>me@example.com</option>
  </select>
  <button id="next" type="button"
    style="position:fixed;left:24px;bottom:24px;width:160px;height:40px">Next</button>
</div>
<script>
  window.__step = 1;
  document.getElementById('next').addEventListener('click', function () {
    window.__step = 2;
    document.getElementById('root').innerHTML =
      '<h2>Apply to Acme</h2>'
      + '<footer><button type="button">Submit application</button></footer>';
  });
</script>
</body></html>
"""

_OVERLAY_GEOMETRY_JS = """() => {
  const panel = document.getElementById('autojob-status');
  const next = document.getElementById('next');
  if (!panel || !next) return JSON.stringify({ panel: false, next: false });
  const a = panel.getBoundingClientRect();
  const b = next.getBoundingClientRect();
  const overlap = !(a.right < b.left || a.left > b.right || a.bottom < b.top || a.top > b.bottom);
  return JSON.stringify({
    panel: true,
    next: true,
    overlap: overlap,
    pointer_events: getComputedStyle(panel).pointerEvents,
    step: window.__step
  });
}"""


async def test_status_panel_does_not_swallow_the_next_click(tmp_path: Path) -> None:
    """BUG-048: the read-only status panel must not block the form's Next button."""
    from src.tools.linkedin_easy_apply_fill import _task4_on_page
    from src.tools.linkedin_status_overlay import _UPDATE_STATUS_JS

    settings = _settings(tmp_path)
    form_file = tmp_path / "overlay_form.html"
    form_file.write_text(_OVERLAY_FORM_HTML, encoding="utf-8")

    browser = browser_tools.build_browser(settings)
    await browser.start()
    try:
        page = await browser.new_page()
        await page.goto(form_file.as_uri())
        await browser_tools._wait_for_load(page, 10)

        # Show the real status panel over the bottom-left area (where Next sits).
        await page.evaluate(_UPDATE_STATUS_JS, "agent", "Self-healing - reopening...")
        geometry = json.loads(await page.evaluate(_OVERLAY_GEOMETRY_JS))
        assert geometry["panel"] is True
        assert geometry["overlap"] is True, (
            "the panel must overlap Next for this test to be meaningful"
        )
        assert geometry["pointer_events"] == "none"

        outcome = await _task4_on_page(
            page,
            browser,
            None,
            {},
            settings,
            lambda _message: None,
            chooser=_no_answer,
        )
        observed = json.loads(await page.evaluate("() => JSON.stringify({step: window.__step})"))
    finally:
        await browser.kill()

    # The click passed through the panel: the form advanced to the terminal step.
    assert outcome.steps_advanced == 1
    assert outcome.reached_terminal_step is True
    assert outcome.submitted is False
    assert observed["step"] == 2
