"""Live Task 32 check: blacklisted companies are skipped on LinkedIn.

Never opens Easy Apply and never submits. Uses a temporary blacklist file (the
real ``blacklist company/companies.json`` is left untouched):

1. Initial scan, empty list: note the first selected job's company (A).
2. Initial scan, list = {A}: A is skipped and a different company is selected.
3. Repeat loop (``open_next_job``): add each newly selected company to the list
   and rescan until nothing eligible remains; the stop must be a clean
   blacklist end.
4. Initial scan with that full list: nothing is selected and the scan ends
   cleanly (``only_blacklisted_jobs_left``).

Live tests use the default search query (``DEFAULT_SEARCH_QUERY``).
"""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from src.configuration import load_settings
from src.state import DEFAULT_LOGIN_URL, DEFAULT_SEARCH_QUERY
from src.tools import company_blacklist as cb
from src.tools.browser import clean_profile, close_run, get_run, start_tasks
from src.tools.linkedin_apply_loop import open_next_job
from src.tools.linkedin_job_apply_button import read_apply_modal


def _use(path: Path, companies: list[str]) -> None:
    path.write_text(json.dumps(companies), encoding="utf-8")
    cb.reset_blacklist_cache()


async def _assert_form_closed(run_id) -> None:
    run = get_run(run_id)
    if run is not None:
        opened, _text = await read_apply_modal(run.page)
        assert not opened, "the Easy Apply form opened"


async def _relaunch_ready(run_id, settings) -> None:
    """Detach the run and force-close its window so the next launch can use the profile."""
    await close_run(run_id)
    clean_profile(settings)


def _check_selected(task2, description, blacklist: frozenset[str]) -> None:
    assert task2.job_selected, f"no job selected: {task2.notes}"
    assert not task2.easy_apply_clicked, "Easy Apply was clicked"
    assert not cb.is_blacklisted(description.company, blacklist), description.company


async def verify(query: str, date_range: str, max_passes: int) -> None:
    settings = load_settings()
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "companies.json"
        cb.BLACKLIST_FILE = path

        _use(path, [])
        result, run_id = await start_tasks(
            DEFAULT_LOGIN_URL, query, settings, progress=print, open_form=False,
            date_range=date_range,
        )
        _check_selected(result.task2, result.job_description, cb.get_blacklist())
        first = result.job_description.company
        assert first, "the first job's company could not be read"
        print(f"PASS 1 baseline: selected {result.task2.job_title!r} at {first!r}")
        await _relaunch_ready(run_id, settings)

        companies = [first]
        _use(path, companies)
        result, run_id = await start_tasks(
            DEFAULT_LOGIN_URL, query, settings, progress=print, open_form=False,
            date_range=date_range,
        )
        _check_selected(result.task2, result.job_description, cb.get_blacklist())
        assert result.task2.blacklisted_jobs_skipped >= 1, "the listed company was not skipped"
        await _assert_form_closed(run_id)
        print(
            f"PASS 2 initial scan: skipped {result.task2.blacklisted_skipped_cards}; "
            f"selected {result.task2.job_title!r} at {result.job_description.company!r}"
        )
        companies.append(result.job_description.company)

        for number in range(max_passes):
            _use(path, companies)
            nxt = await open_next_job(
                run_id, settings, progress=print, date_range=result.task2.date_range_used,
                preferred_range=date_range,
            )
            await _assert_form_closed(run_id)
            if not nxt.opened:
                assert cb.only_blacklisted_jobs_left(nxt.task2), nxt.reason
                print(
                    f"PASS 3 repeat loop: clean end after {number + 1} pass(es), "
                    f"{nxt.task2.blacklisted_jobs_skipped} blacklisted skip(s): {nxt.reason}"
                )
                break
            _check_selected(nxt.task2, nxt.description, cb.get_blacklist())
            print(f"  loop pass {number + 1}: selected {nxt.task2.job_title!r} "
                  f"at {nxt.description.company!r}; blacklisting it")
            companies.append(nxt.description.company)
        else:
            raise AssertionError(f"still finding jobs after {max_passes} passes")
        await _relaunch_ready(run_id, settings)

        _use(path, companies)
        result, run_id = await start_tasks(
            DEFAULT_LOGIN_URL, query, settings, progress=print, open_form=False,
            date_range=date_range,
        )
        assert not result.task2.job_selected and not result.task2.easy_apply_clicked
        assert cb.only_blacklisted_jobs_left(result.task2), result.task2.notes
        print(
            f"PASS 4 all-blacklisted initial scan: {result.task2.blacklisted_jobs_skipped} "
            f"skip(s); notes: {result.task2.notes}"
        )
        await close_run(run_id)
        print(f"companies blacklisted during the check: {companies}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default=DEFAULT_SEARCH_QUERY)
    parser.add_argument("--date-range", default="past_24_hours")
    parser.add_argument("--max-passes", type=int, default=25)
    args = parser.parse_args()
    asyncio.run(verify(args.query, args.date_range, args.max_passes))
