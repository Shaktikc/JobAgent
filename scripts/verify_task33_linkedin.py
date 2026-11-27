"""Live Task 33 check: real CLI crashes on LinkedIn leave one crash bundle each.

Every scenario runs the real console entry (``src.cli.main``) in its own process
against the real LinkedIn site. The crash is injected at ``match``, after
``browse`` has the job page open and **before** any Easy Apply form is opened, so
nothing is filled or submitted. Self-healing bug-log entries go to a temporary
folder (the real ``known Bugs/`` is untouched); crash bundles go to the real
``data/crash_logs`` because that is what is being verified.

Scenarios:

* ``uncaught``  - a graph crash escapes every guard (recursion limit) -> one
  ``uncaught_exception`` bundle with a live screenshot; ``error:`` and exit 1.
* ``node``      - ``match`` crashes with self-healing disabled -> one
  ``node_crash`` bundle with a live screenshot; exit 1.
* ``exhausted`` - self-healing on, one attempt, ``match`` keeps crashing -> one
  ``node_crash`` bundle linking the self-healing bundle and bug id.
* ``recovered`` - self-healing recovers the first crash, then Ctrl+C -> no
  terminal bundle for the recovered crash, one ``interrupted`` bundle, and the
  process stops.

Usage: ``uv run python scripts/verify_task33_linkedin.py`` (all scenarios).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from src.state import DEFAULT_SEARCH_QUERY  # live tests always use the default search

ROOT = Path(__file__).resolve().parent.parent
CRASH_DIR = ROOT / "data" / "crash_logs"
QUERY = DEFAULT_SEARCH_QUERY
ARGV = ["--no-dry-run", "--query", QUERY, "--date-range", "24h", "--submission-mode", "manual"]
REQUIRED = {"crash.json", "report.md", "traceback.txt", "state.json", "run.log", "env.json"}


# --- child: run the real CLI with one injected crash -------------------------


def _child(scenario: str, bug_root: str) -> int:
    import signal

    healing_off = scenario in {"uncaught", "node"}
    os.environ["AUTOJOB_SELF_HEAL_ENABLED"] = "false" if healing_off else "true"
    os.environ["AUTOJOB_SELF_HEAL_MAX_ATTEMPTS"] = "1" if scenario == "exhausted" else "2"
    os.environ["AUTOJOB_SELF_HEAL_REPAIR_COMMAND"] = ""  # runtime recovery only

    import src.main as app
    from src.nodes.self_heal_guard import heal_loop
    from src.tools import linkedin_best_matching_resume as resume_tool

    heal_loop.PROJECT_ROOT = Path(bug_root)  # temp bug log, never the real one
    calls = {"n": 0}
    real_ensure_resume = resume_tool.ensure_resume
    real_remember = heal_loop.remember_recovered

    async def injected(*args, **kwargs):
        calls["n"] += 1
        if scenario == "recovered" and calls["n"] > 1:
            return await real_ensure_resume(*args, **kwargs)  # the retry recovers
        raise RuntimeError(f"task33 injected match crash #{calls['n']}")

    def remember_then_interrupt(*args):
        real_remember(*args)
        print("task33-harness: self-healing recovered; pressing Ctrl+C", flush=True)
        signal.raise_signal(signal.SIGINT)  # cancels the run at its next await

    if scenario == "recovered":
        heal_loop.remember_recovered = remember_then_interrupt

    resume_tool.ensure_resume = injected
    if scenario == "uncaught":
        app._recursion_limit = lambda _settings: 2  # ingest, browse, then crash

    from src import cli

    return cli.main(ARGV)


# --- parent: run each scenario and check what it wrote -----------------------


def _index() -> list[dict]:
    path = CRASH_DIR / "index.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _run(scenario: str, bug_root: str) -> tuple[int, str, list[dict]]:
    before = len(_index())
    subprocess.run(["uv", "run", "autojob", "--clean-profile"], cwd=ROOT, check=False,
                   capture_output=True)
    print(f"\n=== scenario {scenario} ===", flush=True)
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child", scenario,
         "--bug-root", bug_root],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=900,
    )
    output = proc.stdout + proc.stderr
    print("\n".join(output.splitlines()[-25:]))
    return proc.returncode, output, _index()[before:]


def _check_bundle(row: dict, *, screenshot: bool) -> dict:
    bundle = ROOT / row["bundle"]
    names = {path.name for path in bundle.iterdir()}
    assert REQUIRED <= names, f"missing files: {REQUIRED - names}"
    record = json.loads((bundle / "crash.json").read_text(encoding="utf-8"))
    if screenshot:
        shot = bundle / "screenshot.png"
        assert shot.is_file() and shot.stat().st_size > 1000, record["browser"]
        assert "linkedin.com" in record["browser"]["page_url"], record["browser"]
    run_log = Path(record["run_log"]["path"])
    assert run_log.is_file(), f"run log missing: {run_log}"
    tail = (bundle / "run.log").read_text(encoding="utf-8").splitlines()
    assert tail and tail[-1].split("] ", 1)[-1] in run_log.read_text(encoding="utf-8")
    return record


def _parent(scenarios: list[str]) -> None:
    bug_root = tempfile.mkdtemp(prefix="task33-bugs-")
    results = {}
    for scenario in scenarios:
        code, output, rows = _run(scenario, bug_root)
        kinds = [row["kind"] for row in rows]
        print(f"--> exit={code} new index rows={kinds}")
        if scenario == "uncaught":
            assert code == 1 and "error: Recursion limit" in output, code
            assert kinds == ["uncaught_exception"], kinds
            record = _check_bundle(rows[0], screenshot=True)
            assert record["stage"] in {"browse", "match"}, record["stage"]
        elif scenario == "node":
            assert code == 1, code
            assert kinds == ["node_crash"], kinds
            record = _check_bundle(rows[0], screenshot=True)
            assert "task33 injected match crash #1" in record["exception"]["traceback"]
        elif scenario == "exhausted":
            assert code == 1, code
            assert kinds == ["node_crash"], kinds
            record = _check_bundle(rows[0], screenshot=False)
            link = record["self_healing"]
            assert link["bug_id"].startswith("BUG-") and link["recovered"] is False, link
            assert Path(link["bundle"]).is_dir(), link
            assert (Path(link["bundle"]) / "screenshot.png").is_file(), "self-heal evidence"
            assert rows[0]["bug_id"] == link["bug_id"]
        elif scenario == "recovered":
            assert code != 0, "Ctrl+C must still stop the process"
            assert "recovered and resumed" in output or "recovered - resumed" in output
            assert kinds == ["interrupted"], kinds
            record = _check_bundle(rows[0], screenshot=True)
            assert record["self_healing"].get("recovered") is True, record["self_healing"]
        results[scenario] = rows[0]["bundle"]
        print(f"PASS {scenario}: {rows[0]['bundle']}")
    subprocess.run(["uv", "run", "autojob", "--clean-profile"], cwd=ROOT, check=False,
                   capture_output=True)
    print("\nALL PASS", json.dumps(results, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child")
    parser.add_argument("--bug-root", default="")
    parser.add_argument("--only", nargs="*",
                        default=["uncaught", "node", "exhausted", "recovered"])
    args = parser.parse_args()
    if args.child:
        raise SystemExit(_child(args.child, args.bug_root))
    _parent(args.only)


if __name__ == "__main__":
    main()
