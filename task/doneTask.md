# Done Tasks

Completed-work log for this project. When a task in `task.md` is finished:

1. Mark it ✅ Done in `task.md`.
2. Add an entry below with the task number, title, date, and the evidence that
   proves it is done (tests, run output, screenshots, or code references).

Keep newest work at the bottom so the log reads chronologically.

| # | Task | Status | Completed |
| - | ---- | ------ | --------- |
| 1 | Log in to LinkedIn, search "software engineer", select Easy Apply | ✅ Done | 2026-10-04 |
| 2 | Select Easy Apply from the job list | ✅ Done | 2026-10-04 |
| 3 | Read the job description and pick the best-matching resume | ⬜ Not started | — |
| 4 | Open Easy Apply and start filling the application form | ⬜ Not started | — |
| 5 | Ask the human for unknown answers, remember them, and show UI feedback | ⬜ Not started | — |

---

## Task 1 — Log in to LinkedIn, search "software engineer", select Easy Apply

**Status:** ✅ Done
**Completed:** 2026-10-04

**What was done**
- Browser session launches (opt-in) and navigates to the LinkedIn login page.
- Login gate: waits for the human to log in before continuing.
- Types `"software engineer"` into the jobs search bar and submits it.
- Selects the **Easy Apply** filter on the results page.

**Evidence**
- `src/tools/browser.py` — `_task1_on_page`, `open_jobs_search`,
  `select_easy_apply_filter`.
- `src/nodes/browse.py` — Task 1 wiring.
- `src/nodes/verify.py` — `_task1_succeeded` acceptance check.
- `tests/unit/test_browser_tools.py`, `tests/integration/test_login_search_live.py`.

---

## Task 2 — Select Easy Apply from the job list

**Status:** ✅ Done
**Completed:** 2026-10-04

**What was done**
- Reads the job list left open by Task 1.
- Opens the first job that offers **Easy Apply**, skipping external-apply jobs.
- Clicks its **Easy Apply** button and confirms the application form opens.
- Stops there — nothing is submitted.

**Evidence**
- `src/tools/browser.py` — `_task2_on_page`, `read_job_cards`,
  `wait_for_job_apply_button`, `wait_for_easy_apply_modal`.
- `src/nodes/verify.py` — `_task2_succeeded` acceptance check.
- `tests/unit/test_browser_tools.py`.

---

<!--
Template for the next completed task:

## Task N — <title>

**Status:** ✅ Done
**Completed:** YYYY-MM-DD

**What was done**
- ...

**Evidence**
- <files, tests, screenshots, run output>
-->
