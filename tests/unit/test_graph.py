"""End-to-end tests for the Task 1 graph (dry-run only: no browser, no network)."""

from __future__ import annotations

import asyncio

from src.graph import _route_after_ingest, graph
from src.nodes.verify import verify
from src.state import DEFAULT_LOGIN_URL, ApplyState, Task1Outcome, new_state


def _run(**kwargs):
    return asyncio.run(graph.ainvoke(new_state(**kwargs)))


def test_new_state_defaults_match_task_inputs() -> None:
    state = new_state()
    assert state["url"] == DEFAULT_LOGIN_URL
    assert state["search_query"] == "software engineer"
    assert state["dry_run"] is True


def test_dry_run_completes_without_launching_a_browser() -> None:
    state = _run(dry_run=True)

    assert state["status"] == "done"
    assert state.get("outcome") is None
    assert state["errors"] == []
    assert any("dry-run" in entry for entry in state["log"])


def test_invalid_url_fails_before_the_browser_node() -> None:
    state = _run(url="https://example.com/login", dry_run=True)

    assert state["status"] == "failed"
    assert state["errors"]
    assert state.get("outcome") is None


def test_empty_url_fails() -> None:
    state = _run(url="", dry_run=True)
    assert state["status"] == "failed"


def test_empty_query_fails() -> None:
    state = _run(search_query="   ", dry_run=True)
    assert state["status"] == "failed"
    assert any("search query" in error for error in state["errors"])


def test_route_after_ingest() -> None:
    assert _route_after_ingest({"status": "failed"}) == "end"
    assert _route_after_ingest({"status": "logging_in"}) == "browse"
    assert _route_after_ingest({}) == "browse"


def test_verify_passes_when_all_criteria_are_met() -> None:
    state = ApplyState(
        dry_run=False,
        outcome=Task1Outcome(
            logged_in=True,
            results_found=True,
            results_count=25,
            easy_apply_filter_selected=True,
        ),
    )
    assert verify(state) == {
        "status": "done",
        "log": ["verify: logged in, search returned results, Easy Apply filter selected"],
    }


def test_verify_fails_when_filter_is_not_selected() -> None:
    state = ApplyState(
        dry_run=False,
        outcome=Task1Outcome(logged_in=True, results_found=True, easy_apply_filter_selected=False),
    )
    result = verify(state)
    assert result["status"] == "failed"
    assert result["errors"]


def test_verify_reports_errors_first() -> None:
    state = ApplyState(dry_run=False, errors=["browse: boom"])
    assert verify(state)["status"] == "failed"
