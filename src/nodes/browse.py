"""Drive the browser: log in, search jobs, select Easy Apply (Task 1 steps 1-8).

The real work is delegated to :func:`src.tools.browser.run_task1`, which is
imported lazily so the heavy ``browser`` extra stays optional. That single call
owns one browser session for the whole Task 1 flow, including the human login
gate, so the login cookies carry into the search.
"""

from __future__ import annotations

from src.state import ApplyState


async def browse(state: ApplyState) -> ApplyState:
    """Run the login + search + Easy Apply filter flow."""
    if state.get("dry_run", True):
        return {
            "status": "dry_run",
            "log": ["browse: dry-run, browser not launched"],
        }

    from src.tools.browser import run_task1  # lazy: needs the `browser` extra

    try:
        outcome = await run_task1(
            state["url"],
            state.get("search_query") or "",
            progress=print,
        )
    except Exception as exc:  # noqa: BLE001 - surface any setup/launch failure
        return {
            "status": "failed",
            "errors": [f"browse: {exc}"],
            "log": ["browse: browser run failed"],
        }

    log = [
        "browse: "
        f"logged_in={outcome.logged_in} "
        f"results_found={outcome.results_found} "
        f"results_count={outcome.results_count} "
        f"easy_apply_filter={outcome.easy_apply_filter_selected}"
    ]
    if outcome.notes:
        log.append(f"browse: {outcome.notes}")

    update: ApplyState = {"outcome": outcome, "status": "searched", "log": log}
    if not outcome.logged_in:
        update["errors"] = [f"browse: login not completed (url={outcome.page_url or state['url']})"]
    elif not outcome.results_found:
        update["errors"] = [
            f"browse: job search returned no results (url={outcome.page_url or state['url']})"
        ]
    elif not outcome.easy_apply_filter_selected:
        update["errors"] = [f"browse: Easy Apply filter not selected (url={outcome.page_url})"]
    return update
