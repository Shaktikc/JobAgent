"""Task 1: log in to LinkedIn, search jobs, and apply the results filters.

The package keeps the original ``src.tools.linkedin_search`` public API as a
thin re-export facade, so ``browser``'s lazy re-exports and existing callers keep
working unchanged. The implementation is grouped by concern:

* :mod:`.common` — the one-control-at-a-time click settle.
* :mod:`.search_box` — login state, the jobs search bar, and the search results.
* :mod:`.easy_apply_filter` — find/select/verify the **Easy Apply** filter.
* :mod:`.ai_search` — the optional "Try AI job search" detour.
* :mod:`.orchestrator` — the Task 1 step sequence, including Task 13's
  **Date posted → Past 24 hours** filter.
"""

from __future__ import annotations

from src.tools.linkedin_search.ai_search import (
    _AI_CANDIDATES_QUERY,
    _MAX_AI_JOB_SEARCH_CLICKS,
    click_ai_job_search,
    find_ai_job_search_button,
    read_ai_job_search_candidates,
    run_ai_job_search_detour,
    wait_for_ai_job_search_button,
)
from src.tools.linkedin_search.common import _settle_after_click
from src.tools.linkedin_search.easy_apply_filter import (
    _EASY_APPLY_FILTER_SELECTORS,
    _FILTER_QUERY,
    easy_apply_filter_selected,
    find_easy_apply_filter,
    select_easy_apply_filter,
)
from src.tools.linkedin_search.orchestrator import (
    _task1_ok,
    _task1_on_page,
    run_task1,
)
from src.tools.linkedin_search.search_box import (
    _JOBS_SEARCH_INPUT_SELECTORS,
    _JOBS_SEARCH_SUBMIT_SELECTORS,
    _JOBS_TAB_URL,
    _LOGIN_STATE_QUERY,
    find_jobs_search_input,
    is_logged_in,
    open_jobs_search,
    type_jobs_search,
    wait_for_login,
)

__all__ = [
    "_AI_CANDIDATES_QUERY",
    "_EASY_APPLY_FILTER_SELECTORS",
    "_FILTER_QUERY",
    "_JOBS_SEARCH_INPUT_SELECTORS",
    "_JOBS_SEARCH_SUBMIT_SELECTORS",
    "_JOBS_TAB_URL",
    "_LOGIN_STATE_QUERY",
    "_MAX_AI_JOB_SEARCH_CLICKS",
    "_settle_after_click",
    "_task1_ok",
    "_task1_on_page",
    "click_ai_job_search",
    "easy_apply_filter_selected",
    "find_ai_job_search_button",
    "find_easy_apply_filter",
    "find_jobs_search_input",
    "is_logged_in",
    "open_jobs_search",
    "read_ai_job_search_candidates",
    "run_ai_job_search_detour",
    "run_task1",
    "select_easy_apply_filter",
    "type_jobs_search",
    "wait_for_ai_job_search_button",
    "wait_for_login",
]
