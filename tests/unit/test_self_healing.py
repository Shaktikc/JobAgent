"""Offline tests for the Task 11 self-healing loop."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from src.configuration import SelfHealingSettings, Settings
from src.state import FormField, JobDescription, Task2Outcome, Task4Outcome, Task5Outcome
from src.tools import browser as browser_tools
from src.tools.self_healing import buglog
from src.tools.self_healing.capture import capture_failure
from src.tools.self_healing.fingerprint import (
    classify_failure,
    fill_failure_reason,
    is_recoverable,
)
from src.tools.self_healing.loop import HealResult, heal_fill_failure
from src.tools.self_healing.models import (
    CapturedFailure,
    FailureEvidence,
    FailureRecord,
    JobTarget,
    SelfHealingOutcome,
)
from src.tools.self_healing.recovery import ReopenResult, close_run_force


async def _value(value):
    return value


def _settings(tmp_path: Path, **healing) -> Settings:
    healing.setdefault("max_repair_attempts", 3)
    return Settings(
        self_healing=SelfHealingSettings(**healing),
        data_dir=tmp_path / "data",
    )


def _failed_fill() -> Task4Outcome:
    return Task4Outcome(
        form_open=True,
        resume_attached=False,
        notes="no resume control found on this form step",
    )


def _successful_fill() -> Task4Outcome:
    return Task4Outcome(
        form_open=True,
        resume_attached=True,
        resume_selection="listed",
        resume_listed_name="a.pdf",
    )


def _captured(tmp_path: Path) -> CapturedFailure:
    return CapturedFailure(
        fingerprint="loopfingerprint",
        category="resume_control_missing",
        symptom="no resume control",
        bundle_dir=str(tmp_path / "bundle"),
        evidence=FailureEvidence(error="no resume control found"),
    )


def _record(tmp_path: Path) -> FailureRecord:
    (tmp_path / "bundle").mkdir(parents=True, exist_ok=True)
    return FailureRecord(
        fingerprint="loopfingerprint",
        category="resume_control_missing",
        bug_id="BUG-900",
        bug_path=str(tmp_path / "known Bugs" / "self_healing_bugs.md"),
        bundle_dir=str(tmp_path / "bundle"),
        symptom="no resume control",
    )

def _reopened() -> ReopenResult:
    return ReopenResult(
        run_id="run-2",
        task2=Task2Outcome(job_title="Backend Engineer", application_form_opened=True),
        description=JobDescription(title="Backend Engineer", company="Acme"),
    )

# --- classification / fingerprinting ---------------------------------------

def test_no_resume_control_is_recoverable() -> None:
    outcome = _failed_fill()
    category = classify_failure("", outcome)
    assert category == "resume_control_missing"
    assert is_recoverable(category, outcome) is True
    assert "no resume control" in fill_failure_reason(outcome)


def test_required_unknown_question_is_not_auto_retried() -> None:
    outcome = Task4Outcome(
        form_open=True,
        resume_attached=True,
        fields=[FormField(question="Clearance?", required=True, known=False)],
    )
    category = classify_failure("", outcome)
    assert category == "required_question_unanswered"
    assert is_recoverable(category, outcome) is False


def test_a_stuck_step_outranks_the_missing_resume_note() -> None:
    """When both notes are present, the real stop (a stuck step) is the category.

    BUG-048 recorded ``resume_control_missing`` because the walk notes mention the
    missing resume control first, even though the actual stop was "form did not
    advance". The advance failure is the actionable one.
    """
    outcome = Task4Outcome(
        form_open=True,
        resume_attached=False,
        notes=(
            "no resume control found on this form step; "
            "form did not advance to a new step"
        ),
    )
    assert classify_failure("", outcome) == "form_did_not_advance"

# --- evidence capture ------------------------------------------------------

class _FakeSession:
    def __init__(self) -> None:
        self.killed = False

    async def take_screenshot(self, *, path: str, full_page: bool = True) -> None:
        Path(path).write_bytes(b"png")

    async def kill(self) -> None:
        self.killed = True


class _FakePage:
    async def evaluate(self, js: str, *args):
        if "__autojobConsoleInstalled" in js:
            return "true"
        if "data-autojob-fill" in js:
            return json.dumps(
                {
                    "open": True,
                    "title": "Apply to Acme",
                    "step": "2/3 pages",
                    "fields": [
                        {
                            "kind": "text",
                            "question": "Phone",
                            "name": "phone",
                            "required": True,
                        }
                    ],
                }
            )
        if "data-autojob-btn" in js:
            return json.dumps({"buttons": [{"text": "Next", "disabled": False}]})
        if "data-autojob-resume" in js:
            return json.dumps({"options": [], "fileInput": False})
        if "visible_text" in js:
            return json.dumps(
                {
                    "url": "https://www.linkedin.com/jobs/view/1",
                    "title": "Easy Apply",
                    "visible_text": "Apply to Acme",
                    "dom_excerpt": "<div class='modal'>...</div>",
                    "console": ["error: boom"],
                }
            )
        return ""

    async def get_url(self) -> str:
        return "https://www.linkedin.com/jobs/view/1"


async def test_capture_writes_the_bundle(tmp_path: Path) -> None:
    run_id = "heal-capture"
    session = _FakeSession()
    browser_tools._ACTIVE_RUNS[run_id] = browser_tools._Run(
        session=session, page=_FakePage()
    )
    try:
        captured = await capture_failure(
            run_id,
            _settings(tmp_path),
            stage="fill",
            error="no resume control found",
            task4=_failed_fill(),
            target=JobTarget(title="Backend Engineer", company="Acme"),
        )
    finally:
        browser_tools._ACTIVE_RUNS.pop(run_id, None)

    bundle = Path(captured.bundle_dir)
    assert captured.category == "resume_control_missing"
    for name in ("failure.json", "report.md", "dom.html", "page.txt", "console.log"):
        assert (bundle / name).is_file()
    assert (bundle / "console.log").read_text(encoding="utf-8") == "error: boom"
    assert captured.evidence.step == "2/3 pages"
    assert captured.evidence.fields[0]["question"] == "Phone"
    assert captured.evidence.screenshot_path.endswith("screenshot.png")


# --- bug log ---------------------------------------------------------------


def test_buglog_deduplicates_and_updates_the_index(tmp_path: Path) -> None:
    bug_dir = tmp_path / "known Bugs"
    bug_dir.mkdir(parents=True)
    (bug_dir / "task_4_bugs.md").write_text("| BUG-042 | existing |", encoding="utf-8")
    (bug_dir / "bug_log.md").write_text(
        "# Bug Log\n\n| ID | Scope | Symptom | Status | Fix |\n"
        "|----|-------|---------|--------|-----|\n"
        "| BUG-042 | Task 4 | existing | 🟢 Fixed | x |\n\n"
        "## Template for new entries\n",
        encoding="utf-8",
    )
    captured = CapturedFailure(
        fingerprint="abc123",
        category="resume_control_missing",
        symptom="no resume control",
        bundle_dir=str(tmp_path / "bundle"),
        evidence=FailureEvidence(
            error="no resume control found",
            captured_at="2026-10-25T00:00:00+00:00",
        ),
    )

    first = buglog.record_failure(captured, root=tmp_path)
    assert first.bug_id == "BUG-043"
    text = (bug_dir / "self_healing_bugs.md").read_text(encoding="utf-8")
    assert "### BUG-043" in text and "abc123" in text and "🔴 Open" in text

    second = buglog.record_failure(captured, root=tmp_path)
    text = (bug_dir / "self_healing_bugs.md").read_text(encoding="utf-8")
    assert second.bug_id == "BUG-043"
    assert text.count("### BUG-043") == 1
    assert "Occurrences:** 2" in text

    assert buglog.update_bug(
        "BUG-043",
        status="🟢 Fixed",
        fix="recovered by reopening the same job",
        evidence="bundle and live check",
        root=tmp_path,
    )
    index = (bug_dir / "bug_log.md").read_text(encoding="utf-8")
    assert "| BUG-043 |" in index and "🟢 Fixed" in index


# --- browser lifecycle -----------------------------------------------------


async def test_close_run_force_kills_the_given_run(tmp_path, monkeypatch) -> None:
    run_id = "heal-close"
    session = _FakeSession()
    browser_tools._ACTIVE_RUNS[run_id] = browser_tools._Run(session=session, page=_FakePage())
    monkeypatch.setattr(browser_tools, "_profile_browser_pids", lambda _profile: [])
    monkeypatch.setattr(browser_tools, "_clear_profile_locks", lambda _profile: None)
    closed, detail = await close_run_force(run_id, _settings(tmp_path))
    browser_tools._ACTIVE_RUNS.pop(run_id, None)
    assert closed is True
    assert session.killed is True
    assert "closed" in detail


# --- bounded loop ----------------------------------------------------------


async def test_loop_recovers_by_reopening_the_same_job(tmp_path: Path) -> None:
    calls: list[str] = []

    async def fake_reopen(target, settings, notify):
        calls.append("reopen")
        return _reopened()

    async def fake_fill(run_id, resume_path, settings=None, progress=None):
        calls.append(f"fill:{run_id}")
        return _successful_fill(), Task5Outcome(enabled=True, asked=1, answered=1)

    result = await heal_fill_failure(
        run_id="run-1",
        task4=_failed_fill(),
        task5=Task5Outcome(),
        settings=_settings(tmp_path),
        target=JobTarget(title="Backend Engineer"),
        resume_path="resumes/a.pdf",
        capture_fn=lambda *a, **k: _value(_captured(tmp_path)),
        record_fn=lambda captured: _record(tmp_path),
        close_fn=lambda run_id, settings: _value((True, "closed")),
        reopen_fn=fake_reopen,
        fill_fn=fake_fill,
    )

    assert result.recovered is True
    assert result.run_id == "run-2"
    assert result.outcome.attempts == 1
    assert result.outcome.bug_ids == ["BUG-900"]
    assert calls == ["reopen", "fill:run-2"]
    assert result.task4 is not None and result.task4.resume_attached is True


async def test_loop_stops_after_the_attempt_cap(tmp_path: Path) -> None:
    async def fake_capture(*args, **kwargs):
        return _captured(tmp_path)

    async def fake_fill(run_id, resume_path, settings=None, progress=None):
        return _failed_fill(), Task5Outcome()

    result = await heal_fill_failure(
        run_id="run-1",
        task4=_failed_fill(),
        task5=Task5Outcome(),
        settings=_settings(tmp_path, max_repair_attempts=2),
        target=JobTarget(title="Backend Engineer"),
        resume_path="resumes/a.pdf",
        capture_fn=fake_capture,
        record_fn=lambda captured: _record(tmp_path),
        close_fn=lambda run_id, settings: _value((True, "closed")),
        reopen_fn=lambda target, settings, notify: _value(_reopened()),
        fill_fn=fake_fill,
    )

    assert result.recovered is False
    assert result.outcome.attempts == 2
    assert result.outcome.exhausted is True
    assert result.errors
    assert any("stopping" in line for line in result.log)


async def test_repair_failure_stops_before_reopening(tmp_path: Path) -> None:
    commands: list[str] = []
    reopened = False

    async def fake_command(command, cwd, env, timeout):
        commands.append(command)
        return 1, "test failure"

    async def fake_reopen(target, settings, notify):
        nonlocal reopened
        reopened = True
        return _reopened()

    result = await heal_fill_failure(
        run_id="run-1",
        task4=_failed_fill(),
        task5=Task5Outcome(),
        settings=_settings(
            tmp_path,
            max_repair_attempts=3,
            repair_command="repair",
            test_command="pytest",
        ),
        target=JobTarget(title="Backend Engineer"),
        resume_path="resumes/a.pdf",
        capture_fn=lambda *a, **k: _value(_captured(tmp_path)),
        record_fn=lambda captured: _record(tmp_path),
        close_fn=lambda run_id, settings: _value((True, "closed")),
        reopen_fn=fake_reopen,
        fill_fn=lambda *a, **k: _value((_successful_fill(), Task5Outcome())),
        command_fn=fake_command,
    )

    assert result.recovered is False
    assert reopened is False
    assert commands == ["repair"]
    assert "repair command failed" in result.outcome.stop_reason
    assert (tmp_path / "bundle" / "repair.log").is_file()


# --- fill-node integration -------------------------------------------------


async def test_fill_node_uses_the_healing_result(monkeypatch, tmp_path: Path) -> None:
    fill_node = importlib.import_module("src.nodes.fill")
    healing_loop = importlib.import_module("src.tools.self_healing.loop")
    settings = _settings(tmp_path, max_repair_attempts=2)
    monkeypatch.setattr(fill_node, "load_settings", lambda: settings)

    async def fake_fill(run_id, resume_path, settings=None, progress=None):
        return _failed_fill(), Task5Outcome()

    async def fake_heal(**kwargs):
        return HealResult(
            recovered=True,
            run_id="run-2",
            task4=_successful_fill(),
            task5=Task5Outcome(),
            task2=Task2Outcome(job_title="Backend Engineer", application_form_opened=True),
            description=JobDescription(title="Backend Engineer"),
            outcome=SelfHealingOutcome(enabled=True, attempts=1, recovered=True),
            log=["self-heal: recovered"],
        )

    monkeypatch.setattr(browser_tools, "fill_application", fake_fill)
    monkeypatch.setattr(healing_loop, "heal_fill_failure", fake_heal)
    state = {
        "dry_run": False,
        "browser_run_id": "run-1",
        "url": "https://www.linkedin.com/login/",
        "search_query": "python",
        "task2": Task2Outcome(job_title="Backend Engineer"),
        "job_description": JobDescription(title="Backend Engineer"),
        "task3": type("Task3", (), {"selected_path": "resumes/a.pdf"})(),
    }

    result = await fill_node.fill(state)

    assert result["task4"].resume_attached is True
    assert result["browser_run_id"] == "run-2"
    assert result["self_healing"].recovered is True
    assert not result.get("errors")
    assert any("recovered" in line for line in result["log"])
