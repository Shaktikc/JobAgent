"""Task 33: crash bundles, the index, redaction, clipping, and dedupe."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cli_crash_logging import record_returned_failure, stream_graph
from src.state import JobDescription
from src.tools import crash_logs
from src.tools.crash_logs import browser as browser_capture
from src.tools.crash_logs import store
from src.tools.crash_logs.config import load_crash_config
from src.tools.crash_logs.log_tee import RunLog
from src.tools.crash_logs.redact import Clipper
from src.tools.crash_logs.runtime import reset_run_context
from src.tools.self_healing.models import SelfHealingOutcome


@pytest.fixture
def crash_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("AUTOJOB_CRASH_LOG_ENABLED", "true")
    context = reset_run_context(argv=["autojob", "--no-dry-run"])
    context.config = load_crash_config(tmp_path / "data")
    context.run_log = RunLog(tmp_path / "data" / "logs" / "run-test.log")
    return tmp_path / "data" / "crash_logs"


def _raise_chained():
    try:
        raise TimeoutError("CDP timed out")
    except TimeoutError as inner:
        raise RuntimeError("fill crashed") from inner


def _crash() -> BaseException:
    try:
        _raise_chained()
    except RuntimeError as exc:
        return exc
    raise AssertionError("unreachable")


def _bundles(crash_dir: Path) -> list[Path]:
    return sorted(path for path in crash_dir.iterdir() if path.is_dir())


def _index(crash_dir: Path) -> list[dict]:
    return json.loads((crash_dir / "index.json").read_text(encoding="utf-8"))


def _record(bundle: Path) -> dict:
    return json.loads((bundle / "crash.json").read_text(encoding="utf-8"))


def _state() -> dict:
    return {
        "browser_run_id": "run-1",
        "status": "running",
        "log": ["browse: opened job", "fill: step 2"],
        "errors": [],
        "job_description": JobDescription(
            title="Backend Engineer", company="Acme",
            page_url="https://www.linkedin.com/jobs/view/4401234567/",
        ),
    }


def test_first_crash_writes_a_complete_bundle_and_index(crash_dir):
    run_log = crash_logs.run_context().run_log
    run_log.write_line("out", "agent: filling step 2")
    crash_logs.note_state(_state(), "fill")

    bundle = Path(crash_logs.record_exception(_crash(), exit_code=1))

    names = {path.name for path in bundle.iterdir()}
    assert {"crash.json", "report.md", "traceback.txt", "state.json",
            "run.log", "env.json"} <= names
    record = _record(bundle)
    assert record["kind"] == "uncaught_exception" and record["stage"] == "fill"
    assert record["exception"]["type"] == "RuntimeError"
    assert record["exception"]["message"] == "fill crashed"
    assert record["exception"]["chain"][0]["type"] == "TimeoutError"
    assert "CDP timed out" in record["exception"]["traceback"]
    assert any(frame["function"] == "_raise_chained" for frame in record["exception"]["frames"])
    assert record["job"] == {"id": "4401234567", "title": "Backend Engineer", "company": "Acme",
                             "url": "https://www.linkedin.com/jobs/view/4401234567/"}
    assert record["run"]["argv"] == ["autojob", "--no-dry-run"] and record["run"]["python"]
    assert record["state"]["log"] == ["browse: opened job", "fill: step 2"]
    assert "agent: filling step 2" in (bundle / "run.log").read_text(encoding="utf-8")
    assert record["run_log"]["path"].endswith("run-test.log")
    assert "fill crashed" in (bundle / "traceback.txt").read_text(encoding="utf-8")
    env = json.loads((bundle / "env.json").read_text(encoding="utf-8"))
    assert "settings" in env and env["pid"] == record["run"]["pid"]
    rows = _index(crash_dir)
    assert len(rows) == 1 and rows[0]["exception_type"] == "RuntimeError"
    assert rows[0]["job_title"] == "Backend Engineer" and rows[0]["exit_code"] == 1
    assert (crash_dir / "index.json").read_text(encoding="utf-8").endswith("]\n")


def test_second_crash_appends_without_touching_the_first(crash_dir):
    first = Path(crash_logs.record_crash("returned_failure", state=_state(), message="one"))
    before = (first / "crash.json").read_bytes()
    second = Path(crash_logs.record_crash("returned_failure", state=_state(), message="two"))
    assert first != second
    assert (first / "crash.json").read_bytes() == before
    assert [row["message"] for row in _index(crash_dir)] == ["one", "two"]


def test_unreadable_index_is_quarantined(crash_dir):
    crash_dir.mkdir(parents=True)
    (crash_dir / "index.json").write_text("{not json", encoding="utf-8")
    crash_logs.record_crash("returned_failure", state=_state(), message="after corrupt")
    quarantined = list(crash_dir.glob("index.corrupt-*.json"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{not json"
    assert [row["message"] for row in _index(crash_dir)] == ["after corrupt"]


def test_bundle_write_failure_is_reported_and_never_raises(crash_dir, monkeypatch, capsys):
    def fail(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(store, "write_atomic", fail)
    assert crash_logs.record_exception(_crash()) is None
    assert "could not write the crash bundle (disk full)" in capsys.readouterr().err


def test_redaction_removes_secrets_and_sensitive_answers(crash_dir):
    state = {
        **_state(),
        "api_key": "sk-or-v1-abcdefghijklmnop",
        "session_token": "tok-123",
        "token_usage": {"total_tokens": 1234},
        "log": ["calling LLM with Authorization: Bearer abc.def.ghi"],
        "task4": {"fields": [
            {"label": "Social Security Number", "value": "123-45-6789"},
            {"label": "Account password", "answer": "hunter2"},
            {"label": "Years of Python", "value": "5"},
        ]},
    }
    bundle = Path(crash_logs.record_crash("returned_failure", state=state, message="x"))
    text = (bundle / "state.json").read_text(encoding="utf-8")
    for secret in ("sk-or-v1-abcdefghijklmnop", "tok-123", "123-45-6789", "hunter2",
                   "abc.def.ghi"):
        assert secret not in text
        assert secret not in (bundle / "crash.json").read_text(encoding="utf-8")
    saved = json.loads(text)
    assert saved["task4"]["fields"][0]["label"] == "Social Security Number"
    assert saved["task4"]["fields"][2]["value"] == "5"
    assert saved["token_usage"]["total_tokens"] == 1234


def test_clipping_caps_strings_lists_and_records_it(crash_dir):
    state = {**_state(), "notes": "x" * 5000, "items": list(range(500))}
    bundle = Path(crash_logs.record_crash("returned_failure", state=state, message="clip"))
    saved = json.loads((bundle / "state.json").read_text(encoding="utf-8"))
    assert len(saved["notes"]) < 2100 and len(saved["items"]) == 200
    report = (bundle / "report.md").read_text(encoding="utf-8")
    assert "state.notes clipped from 5000" in report
    assert "state.items clipped from 500 to 200 items" in report


class _Run:
    page = object()
    session = object()


async def test_live_page_is_captured_and_dom_console_are_clipped(crash_dir, monkeypatch):
    from src.tools.self_healing import capture

    async def snapshot(_page):
        return {"url": "https://www.linkedin.com/jobs/view/1/", "title": "Job",
                "dom_excerpt": "<div>" + "d" * 70_000, "visible_text": "Apply",
                "console": [f"error: {n}" for n in range(100)]}

    async def screenshot(_run, path):
        path.write_bytes(b"\x89PNG")
        return str(path)

    monkeypatch.setattr(browser_capture, "_live_run", lambda run_id: (run_id, _Run()))
    monkeypatch.setattr(capture, "_page_snapshot", snapshot)
    monkeypatch.setattr(capture, "_take_screenshot", screenshot)
    path = await crash_logs.record_crash_async("node_crash", exc=_crash(), state=_state())
    bundle = Path(path)
    browser = _record(bundle)["browser"]
    assert browser["page_url"] == "https://www.linkedin.com/jobs/view/1/"
    assert browser["screenshot"] == "screenshot.png" and browser["error"] == ""
    assert (bundle / "screenshot.png").read_bytes() == b"\x89PNG"
    assert len((bundle / "dom.html").read_text(encoding="utf-8")) <= 60_020
    console = (bundle / "console.log").read_text(encoding="utf-8").splitlines()
    assert len(console) == 80 and console[-1] == "error: 99"


async def test_dead_page_records_browser_error_without_hiding_the_crash(crash_dir, monkeypatch):
    from src.tools.self_healing import capture

    async def dead(_page):
        raise ConnectionError("CDP socket closed")

    monkeypatch.setattr(browser_capture, "_live_run", lambda run_id: (run_id, _Run()))
    monkeypatch.setattr(capture, "_page_snapshot", dead)
    bundle = Path(await crash_logs.record_crash_async("node_crash", exc=_crash(), state=_state()))
    record = _record(bundle)
    assert "CDP socket closed" in record["browser"]["error"]
    assert record["exception"]["message"] == "fill crashed"


def test_returned_failure_without_exception_writes_a_bundle(crash_dir):
    state = {**_state(), "status": "failed", "errors": ["verify: acceptance criteria not met"]}
    bundle = Path(record_returned_failure(state, 1))
    record = _record(bundle)
    assert record["kind"] == "returned_failure" and record["exit_code"] == 1
    assert record["errors"] == ["verify: acceptance criteria not met"]
    assert (bundle / "traceback.txt").read_text(encoding="utf-8").strip() == "(none)"


def test_returned_failure_skips_login_gate_and_done(crash_dir):
    assert record_returned_failure({"status": "done"}, 0) is None
    gate = {"status": "failed", "errors": ["browse: login not completed (url=x)"]}
    assert record_returned_failure(gate, 1) is None
    assert not crash_dir.exists() or not _bundles(crash_dir)


def test_self_healing_evidence_is_linked_not_copied(crash_dir):
    outcome = SelfHealingOutcome(enabled=True, attempts=3, exhausted=True,
                                 bug_ids=["BUG-129"], last_bundle="data/debug/self_healing/b1")
    bundle = Path(crash_logs.record_crash(
        "node_crash", exc=_crash(), state={**_state(), "self_healing": outcome}))
    link = _record(bundle)["self_healing"]
    assert link["bug_id"] == "BUG-129" and link["bundle"] == "data/debug/self_healing/b1"
    assert link["attempts"] == 3 and link["recovered"] is False
    assert not (bundle / "screenshot.png").exists()
    assert _index(crash_dir)[0]["bug_id"] == "BUG-129"


async def test_one_bundle_when_node_guard_and_cli_see_the_same_crash(crash_dir):
    exc = _crash()
    await crash_logs.record_crash_async("node_crash", exc=exc, state=_state(),
                                        capture_page=False)
    assert crash_logs.record_exception(exc, exit_code=1) is None
    state = {**_state(), "status": "failed", "errors": ["fill: fill crashed"]}
    assert record_returned_failure(state, 1) is None
    assert len(_bundles(crash_dir)) == 1


async def test_stream_graph_returns_final_state_and_records_a_graph_crash(crash_dir):
    class Graph:
        def __init__(self, fail):
            self.fail = fail

        async def astream(self, state, config, stream_mode):
            yield {**state, "stage": 1}
            if self.fail:
                raise RuntimeError("graph boom")
            yield {**state, "status": "done"}

    final = await stream_graph(Graph(False), {"status": "running"}, {})
    assert final == {"status": "done"}
    with pytest.raises(RuntimeError, match="graph boom"):
        await stream_graph(Graph(True), {"browser_run_id": "r9"}, {})
    record = _record(_bundles(crash_dir)[0])
    assert record["state"] == {"browser_run_id": "r9", "stage": 1}


def test_disabled_crash_logging_writes_nothing(crash_dir, monkeypatch):
    crash_logs.run_context().config.enabled = False
    assert crash_logs.record_exception(_crash()) is None
    assert not crash_dir.exists()


def test_retention_prunes_only_when_set(crash_dir):
    config = crash_logs.run_context().config
    config.max_bundles = 2
    for n in range(3):
        crash_logs.record_crash("returned_failure", state=_state(), message=f"m{n}")
    assert len(_bundles(crash_dir)) == 2
    assert len(_index(crash_dir)) == 3  # the index is append-only


def test_clipper_marks_deep_values():
    clipper = Clipper()
    value: dict = {}
    cursor = value
    for _ in range(20):
        cursor["next"] = {}
        cursor = cursor["next"]
    clipper.clean(value)
    assert any("deeper" in note for note in clipper.notes)


async def test_cleanup_crash_is_recorded_and_re_raised_unchanged(crash_dir):
    from src.nodes.cleanup_guard import guard_cleanup

    async def cleanup(_state):
        raise RuntimeError("release failed")

    with pytest.raises(RuntimeError, match="release failed"):
        await guard_cleanup(cleanup)(_state())
    [bundle] = _bundles(crash_dir)
    record = _record(bundle)
    assert record["kind"] == "cleanup_crash" and record["stage"] == "cleanup"
    # The CLI later sees the same exception; it must not write a second bundle.
    assert crash_logs.already_recorded(RuntimeError("other")) is False
