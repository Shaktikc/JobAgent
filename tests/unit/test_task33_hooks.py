"""Task 33: global hooks, Ctrl+C, the closed-pipe filter, CLI paths, and the run-log tee."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.cli_crash_logging import stream_graph
from src.tools import crash_logs
from src.tools.crash_logs import hooks
from src.tools.crash_logs.log_tee import RunLog, TeeStream, install_tee


@pytest.fixture
def data_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("AUTOJOB_CRASH_LOG_ENABLED", "true")
    monkeypatch.setenv("AUTOJOB_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def _kinds(data_dir: Path) -> list[str]:
    index = data_dir / "crash_logs" / "index.json"
    if not index.exists():
        return []
    return [row["kind"] for row in json.loads(index.read_text(encoding="utf-8"))]


def _error() -> BaseException:
    try:
        raise RuntimeError("hook boom")
    except RuntimeError as exc:
        return exc


def test_excepthook_records_then_calls_the_previous_hook(data_dir, monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: seen.append(args[1]))
    crash_logs.install_crash_logging(["autojob"], tee=False)
    exc = _error()
    sys.excepthook(type(exc), exc, exc.__traceback__)
    assert seen == [exc]
    assert _kinds(data_dir) == ["uncaught_exception"]
    # Installing twice is a no-op (idempotent).
    crash_logs.install_crash_logging(["autojob"], tee=False)
    assert sys.excepthook is hooks._excepthook


def test_thread_hook_records_the_thread_and_delegates(data_dir, monkeypatch):
    seen = []
    monkeypatch.setattr(threading, "excepthook", lambda args: seen.append(args.thread.name))
    crash_logs.install_crash_logging(["autojob"], tee=False)

    def worker():
        raise ValueError("thread boom")

    thread = threading.Thread(target=worker, name="bg-worker")
    thread.start()
    thread.join()
    assert seen == ["bg-worker"]
    assert _kinds(data_dir) == ["thread_exception"]


def test_unraisable_hook_records_but_filters_the_windows_closed_pipe(data_dir, monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "unraisablehook", lambda unraisable: seen.append(unraisable))
    monkeypatch.setattr(sys, "platform", "win32")
    crash_logs.install_crash_logging(["autojob"], tee=False)
    pipe = SimpleNamespace(exc_value=ValueError("I/O operation on closed pipe"),
                           err_msg="Exception ignored in", object=None)
    other = SimpleNamespace(exc_value=_error(), err_msg="Exception ignored in", object="obj")
    sys.unraisablehook(pipe)
    sys.unraisablehook(other)
    assert seen == [pipe, other]
    assert _kinds(data_dir) == ["unraisable_exception"]


def test_main_keeps_the_closed_pipe_filter_on_top_of_the_crash_hook(data_dir, monkeypatch):
    import src.main as cli

    forwarded = []
    monkeypatch.setattr(sys, "unraisablehook", lambda unraisable: forwarded.append(unraisable))
    monkeypatch.setattr(sys, "platform", "win32")
    crash_logs.install_crash_logging(["autojob"], tee=False)
    cli._silence_windows_pipe_noise()
    sys.unraisablehook(SimpleNamespace(exc_value=ValueError("I/O operation on closed pipe")))
    assert forwarded == [] and _kinds(data_dir) == []


async def test_asyncio_handler_records_a_lost_task_exception(data_dir):
    crash_logs.install_crash_logging(["autojob"], tee=False)
    loop = asyncio.get_running_loop()
    previous = []
    loop.set_exception_handler(lambda _loop, context: previous.append(context["message"]))
    crash_logs.install_asyncio_handler(loop)
    loop.call_exception_handler(
        {"message": "Task exception was never retrieved", "exception": _error()}
    )
    assert previous == ["Task exception was never retrieved"]
    assert _kinds(data_dir) == ["asyncio_exception"]
    loop.set_exception_handler(None)


async def test_ctrl_c_inside_the_run_is_recorded_and_re_raised(data_dir):
    crash_logs.install_crash_logging(["autojob"], tee=False)

    class Graph:
        async def astream(self, state, config, stream_mode):
            yield state
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await stream_graph(Graph(), {"status": "running"}, {})
    assert _kinds(data_dir) == ["interrupted"]


def test_keyboard_interrupt_in_main_is_recorded_once_and_re_raised(data_dir, monkeypatch):
    import src.main as cli
    from src.configuration import Settings

    async def interrupted(_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "choose_date_range", lambda value: "past_week")
    monkeypatch.setattr(cli, "_run", interrupted)
    with pytest.raises(KeyboardInterrupt) as raised:
        cli.main(["--no-dry-run", "--query", "python", "--submission-mode", "manual"])
    assert _kinds(data_dir) == ["interrupted"]
    # The excepthook sees the same interrupt later and must not write again.
    monkeypatch.setitem(hooks._PREVIOUS, "excepthook", lambda *args: None)
    hooks._excepthook(KeyboardInterrupt, raised.value, None)
    assert _kinds(data_dir) == ["interrupted"]


def test_cli_graph_crash_keeps_message_and_exit_code(data_dir, monkeypatch, capsys):
    import src.main as cli
    from src.configuration import Settings

    async def crash(_args):
        raise RuntimeError("graph exploded")

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "choose_date_range", lambda value: "past_week")
    monkeypatch.setattr(cli, "_run", crash)
    assert cli.main(["--no-dry-run", "--query", "python", "--submission-mode", "manual"]) == 1
    assert "error: graph exploded" in capsys.readouterr().err
    assert _kinds(data_dir) == ["uncaught_exception"]


def test_describe_failure_is_a_startup_error_with_exit_code_1(data_dir, monkeypatch):
    import src.main as cli

    async def fail(_args):
        raise OSError("intake folder locked")

    monkeypatch.setattr(cli, "_describe_new_resumes", fail)
    assert cli.main(["--describe-new-resumes"]) == 1
    assert _kinds(data_dir) == ["startup_error"]


def test_help_is_not_a_crash(data_dir):
    import src.main as cli

    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert _kinds(data_dir) == []


def test_cli_wrapper_records_an_import_error(data_dir, monkeypatch):
    import builtins

    from src import cli as wrapper

    real_import = builtins.__import__

    def broken(name, *args, **kwargs):
        if name == "src.main":
            raise ImportError("broken import")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken)
    with pytest.raises(ImportError):
        wrapper.main([])
    assert _kinds(data_dir) == ["import_error"]


class _Stream:
    encoding = "utf-8"
    errors = "strict"
    newlines = None
    closed = False

    def __init__(self):
        self.text = ""

    def write(self, text):
        self.text += text
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return True

    def fileno(self):
        return 42


def test_tee_mirrors_lines_and_delegates_stream_attributes(tmp_path):
    run_log = RunLog(tmp_path / "logs" / "run.log")
    out, err = _Stream(), _Stream()
    tee_out, tee_err = TeeStream(out, run_log, "out"), TeeStream(err, run_log, "err")
    tee_out.write("hello ")
    tee_out.write("world\nsecond line\n")
    tee_err.write("an error\n")
    run_log.close()
    assert out.text == "hello world\nsecond line\n" and err.text == "an error\n"
    assert tee_out.isatty() is True and tee_out.fileno() == 42
    assert tee_out.encoding == "utf-8" and tee_out.errors == "strict" and tee_out.closed is False
    lines = (tmp_path / "logs" / "run.log").read_text(encoding="utf-8").splitlines()
    assert lines[0].endswith("[out] hello world") and lines[0][:4].isdigit()
    assert lines[1].endswith("[out] second line") and lines[2].endswith("[err] an error")
    assert run_log.tail_lines()[-1].endswith("[err] an error")


def test_run_log_cap_writes_a_marker_and_keeps_earlier_lines(tmp_path):
    run_log = RunLog(tmp_path / "run.log", max_bytes=200)
    for n in range(20):
        run_log.write_line("out", f"line {n}")
    run_log.close()
    text = (tmp_path / "run.log").read_text(encoding="utf-8")
    assert "line 0" in text and "[run log truncated at 200 bytes" in text
    assert run_log.tail_lines()[-1].endswith("line 19")


def test_tee_is_skipped_under_pytest_and_when_opted_out(data_dir, monkeypatch):
    before = (sys.stdout, sys.stderr)
    assert install_tee(RunLog(None)) is False
    assert (sys.stdout, sys.stderr) == before
    monkeypatch.setenv("AUTOJOB_CRASH_LOG_RUN_LOG", "false")
    context = crash_logs.install_crash_logging(["autojob"], tee=True)
    assert (sys.stdout, sys.stderr) == before
    assert context.run_log.path is None
