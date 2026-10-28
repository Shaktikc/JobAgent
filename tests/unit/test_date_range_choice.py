"""Unit tests for Task 17's startup date-range choice and state wiring."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from src.configuration import SessionSettings, Settings
from src.date_range import (
    DEFAULT_DATE_RANGE,
    PAST_24_HOURS_VALUE,
    PAST_WEEK_VALUE,
    date_range_label,
    date_range_option,
    normalize_date_range,
    other_date_range,
)
from src.date_range_choice import choose_date_range
from src.main import _parse_args
from src.nodes.ingest import ingest
from src.state import ApplyState, Task2Outcome, new_state


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("24h", PAST_24_HOURS_VALUE),
        ("24", PAST_24_HOURS_VALUE),
        ("1", PAST_24_HOURS_VALUE),
        ("Past 24 hours", PAST_24_HOURS_VALUE),
        ("past_24_hours", PAST_24_HOURS_VALUE),
        ("week", PAST_WEEK_VALUE),
        ("7d", PAST_WEEK_VALUE),
        ("2", PAST_WEEK_VALUE),
        ("Past week", PAST_WEEK_VALUE),
        ("past-week", PAST_WEEK_VALUE),
        ("past_month", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_date_range_accepts_aliases(raw, expected) -> None:
    assert normalize_date_range(raw) == expected


def test_range_helpers_pair_each_range_with_its_fallback() -> None:
    assert date_range_label(PAST_24_HOURS_VALUE) == "Past 24 hours"
    assert date_range_label(PAST_WEEK_VALUE) == "Past week"
    assert date_range_option(PAST_24_HOURS_VALUE) == ("Past 24 hours", "r86400")
    assert date_range_option(PAST_WEEK_VALUE) == ("Past week", "r604800")
    assert date_range_option("past_month") == ("", "")
    assert other_date_range(PAST_24_HOURS_VALUE) == PAST_WEEK_VALUE
    assert other_date_range(PAST_WEEK_VALUE) == PAST_24_HOURS_VALUE
    assert other_date_range("") == ""


def test_choose_date_range_uses_an_explicit_value_without_asking() -> None:
    def fail_prompt(_prompt: str) -> str:  # pragma: no cover - must not run
        raise AssertionError("an explicit --date-range must not prompt")

    assert (
        choose_date_range("week", interactive=True, input_func=fail_prompt)
        == PAST_WEEK_VALUE
    )
    assert choose_date_range("24h", interactive=True) == PAST_24_HOURS_VALUE


def test_choose_date_range_rejects_an_unknown_explicit_value() -> None:
    with pytest.raises(ValueError, match="unknown date range"):
        choose_date_range("past_month", interactive=True)


def test_choose_date_range_defaults_without_a_terminal() -> None:
    output = io.StringIO()
    assert (
        choose_date_range(None, interactive=False, stream=output)
        == DEFAULT_DATE_RANGE
    )
    assert output.getvalue() == ""


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("2", PAST_WEEK_VALUE),
        ("week", PAST_WEEK_VALUE),
        ("1", PAST_24_HOURS_VALUE),
        ("", PAST_24_HOURS_VALUE),
        ("24h", PAST_24_HOURS_VALUE),
    ],
)
def test_choose_date_range_prompts_for_either_range(answer, expected) -> None:
    output = io.StringIO()
    selected = choose_date_range(
        None,
        interactive=True,
        input_func=lambda _prompt: answer,
        stream=output,
    )
    assert selected == expected
    assert "Which jobs should I search first?" in output.getvalue()
    assert "fallback: Past week" in output.getvalue()
    assert "fallback: Past 24 hours" in output.getvalue()


def test_choose_date_range_reasks_after_an_invalid_answer() -> None:
    answers = iter(["maybe", "2"])

    selected = choose_date_range(
        None,
        interactive=True,
        input_func=lambda _prompt: next(answers),
        stream=io.StringIO(),
    )

    assert selected == PAST_WEEK_VALUE


def test_cli_parses_and_normalizes_date_range() -> None:
    assert _parse_args([]).date_range is None
    assert _parse_args(["--date-range", "24h"]).date_range == PAST_24_HOURS_VALUE
    assert _parse_args(["--date-range", "week"]).date_range == PAST_WEEK_VALUE
    with pytest.raises(SystemExit):
        _parse_args(["--date-range", "past_month"])


def test_new_state_normalizes_the_startup_range() -> None:
    assert new_state(date_range="week")["date_range"] == PAST_WEEK_VALUE
    assert new_state(date_range="24h")["date_range"] == PAST_24_HOURS_VALUE
    assert new_state(date_range="not-a-range")["date_range"] == DEFAULT_DATE_RANGE


def test_ingest_keeps_the_chosen_range() -> None:
    update = ingest(
        {
            "url": "https://www.linkedin.com/login/",
            "search_query": "software engineer",
            "date_range": "week",
        }
    )

    assert update["date_range"] == PAST_WEEK_VALUE
    assert "date_range=past_week" in update["log"][0]


def test_main_asks_for_the_range_before_the_run(monkeypatch) -> None:
    import src.main as main_mod

    captured: dict = {}

    async def fake_run(args):
        captured["date_range"] = args.date_range
        return {"status": "done", "log": []}

    def fake_choose(value):
        captured["asked_with"] = value
        return PAST_WEEK_VALUE

    monkeypatch.setattr(main_mod, "_run", fake_run)
    monkeypatch.setattr(main_mod, "choose_date_range", fake_choose)

    assert main_mod.main(["--no-dry-run"]) == 0
    assert captured["asked_with"] is None
    assert captured["date_range"] == PAST_WEEK_VALUE


def test_ingest_rejects_an_unknown_range() -> None:
    update = ingest(
        {
            "url": "https://www.linkedin.com/login/",
            "search_query": "software engineer",
            "date_range": "past_month",
        }
    )

    assert update["status"] == "failed"
    assert "unknown date range" in update["errors"][0]


@pytest.mark.asyncio
async def test_task2_forwards_the_preferred_range_to_the_scan(monkeypatch) -> None:
    import src.tools.linkedin_job_selection as jobsel

    captured: dict = {}

    async def fake_scan(
        page, settings, notify, outcome, tried, applied_seen, scan_page, **kwargs
    ):
        captured.update(kwargs)
        outcome.date_range_used = kwargs.get("date_range", "")

    async def get_url():
        return "https://www.linkedin.com/jobs/search-results/?f_TPR=r604800"

    async def get_title():
        return "Jobs"

    page = SimpleNamespace(get_url=get_url, get_title=get_title)
    monkeypatch.setattr(jobsel, "scan_results_pages", fake_scan)

    outcome = await jobsel._task2_on_page(
        page,
        Settings(session=SessionSettings()),
        lambda _m: None,
        date_range=PAST_WEEK_VALUE,
        preferred_range=PAST_WEEK_VALUE,
    )

    assert captured["date_range"] == PAST_WEEK_VALUE
    assert captured["preferred_range"] == PAST_WEEK_VALUE
    assert outcome.date_range_used == PAST_WEEK_VALUE


@pytest.mark.asyncio
async def test_next_job_passes_the_startup_range_to_open_next_job(monkeypatch) -> None:
    import src.nodes.apply_loop as apply_loop
    import src.tools.linkedin_apply_loop as loop

    captured: dict = {}

    async def fake_open(run_id, settings=None, progress=None, **kwargs):
        captured.update(kwargs)
        return loop.NextJobResult(
            opened=True,
            task2=Task2Outcome(job_title="Older Week Job", job_selected=True),
        )

    monkeypatch.setattr(loop, "open_next_job", fake_open)
    state = ApplyState(
        dry_run=False,
        browser_run_id="run-1",
        date_range=PAST_WEEK_VALUE,
        task2=Task2Outcome(job_title="Previous Job", date_range_used=PAST_WEEK_VALUE),
    )

    result = await apply_loop.next_job(state)

    assert captured["date_range"] == PAST_WEEK_VALUE
    assert captured["preferred_range"] == PAST_WEEK_VALUE
    assert result["status"] == "applied"
