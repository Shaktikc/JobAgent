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
| 3 | Read the job description and pick the best-matching resume | ✅ Done | 2026-10-04 |
| 4 | Open Easy Apply and start filling the application form | ✅ Done | 2026-10-04 |
| 5 | Ask the human for unknown answers, remember them, and show UI feedback | ✅ Done | 2026-10-04 |

---

## Task 1 — Log in to LinkedIn, search "software engineer", select Easy Apply

**Status:** ✅ Done
**Completed:** 2026-10-04

**What was done**
- Browser session launches (opt-in) and navigates to the LinkedIn login page.
- Login gate: waits for the human to log in before continuing.
- Types `"software engineer"` into the jobs search bar and submits it.
- After the results load, **clicks the "Try AI job Search" button when it is
  present** (optional feature; discovered at runtime). Absence of the button is
  recorded (`ai_job_search_present=False`) and never fails the run; a failed
  click is noted instead of aborting.
- Selects the **Easy Apply** filter on the results page.

**Evidence**
- `src/tools/browser.py` — `_task1_on_page`, `open_jobs_search`,
  `find_ai_job_search_button`, `click_ai_job_search`,
  `select_easy_apply_filter`.
- `src/tools/linkedin.py` — `looks_like_ai_job_search`, `pick_ai_job_search_index`.
- `src/state.py` — `Task1Outcome.ai_job_search_present` / `ai_job_search_clicked`.
- `src/nodes/browse.py` — Task 1 wiring/log; `src/main.py` — summary line.
- `src/nodes/verify.py` — `_task1_succeeded` acceptance check.
- `tests/unit/test_browser_tools.py`, `tests/unit/test_linkedin.py`,
  `tests/integration/test_login_search_live.py`.

**Update (2026-10-05):** added the optional "Try AI job Search" click after the
search, then hardened it after a real run showed the button was not being
clicked:
- Discovery is now a runtime JS scan (`_AI_CANDIDATES_QUERY`) of all interactive
  controls (`button`, `a`, `[role=button]`, `[role=link]`, `[role=tab]`, button
  inputs) instead of a fixed `<button>` selector, so link/role-based markup is
  found too.
- The label combines `aria-label`, `title`, visible text, and `value`, so a
  control whose accessible name differs from its visible "Try AI job search"
  text still matches.
- Matching is broader: any label with an `AI` token (or "Artificial
  Intelligence") that also mentions "search" — e.g. "Try AI-powered job search",
  "Search with AI", "AI-powered search" — while "Save this search" and
  "AI resume builder" are excluded.
- The control is polled briefly after results load (configurable
  `AUTOJOB_SESSION_AI_SEARCH_TIMEOUT_SECONDS`, default 5s) so a late-rendering
  button is still clicked; absence still never fails the run.
- After a successful AI job search click, Task 1 **repeats the job search**
  ("software engineer" typed and submitted again) before selecting the Easy
  Apply filter. The repeat happens only after a successful click, so an absent
  or unclickable button still searches exactly once (no loop).
- **Fix (click navigates/reloads the page):** clicking "Try AI job search"
  navigates/reloads LinkedIn, and such a click can make `Element.click()` raise
  after the navigation already started (the CDP execution context is destroyed).
  That exception used to be treated as a failed click, so the repeat search never
  ran. Now a changed URL counts as a successful click, and the page load is
  awaited after the click before repeating the search.
- **Fix (self-inflicted page reloads):** `type_jobs_search` used to
  `page.goto` the Jobs tab on *every* search, and `open_jobs_search` fell back to
  a search-URL navigation. A real user just types in the search bar, so the agent
  now types **in place** and opens the Jobs tab only when the search bar is not
  already on the page. The repeat search after an AI click never navigates
  (`open_jobs_search(..., allow_navigation=False)`), so no page reload occurs.
- **Re-click loop:** while the "Try AI job search" button reappears, the agent
  clicks it again and repeats the search, capped at
  `_MAX_AI_JOB_SEARCH_CLICKS = 3` (the loop stops early if the button disappears
  or a repeat search returns no results). Click count is recorded as
  `Task1Outcome.ai_job_search_clicks` and surfaced in the log/summary.
- **Live browser verification:** `tests/integration/test_task1_ai_search_live.py`
  drives the real `_task1_on_page` in real Chromium against a locally served
  LinkedIn-shaped page (`AUTOJOB_TASK1_LIVE=1`). It proves the runtime scan finds
  and clicks the button, the loop re-clicks until the button removes itself
  (2 clicks), the search is typed in place **without reloading** (`loads == 1`),
  and the Easy Apply filter is selected.
- **Diagnostics for a real-page miss:** when nothing matches, the labels of the
  controls the scan saw are recorded as `Task1Outcome.ai_job_search_candidates`
  and added to the run notes/log, so the actual LinkedIn markup can be reported.
- **Fix (real AI search page found via screenshot):** the "Try AI job search"
  click opens LinkedIn's AI search page, whose only input is the
  **"Describe the job you want"** prompt. That input was not recognised, so the
  repeat search did nothing and the page appeared stuck. `find_jobs_search_input`
  now also matches the AI prompt (`input[placeholder*='Describe the job']` and the
  matching hint), so the repeat search types "software engineer" into it and
  submits with Enter. Covered by the live-browser test
  `test_task1_searches_via_the_ai_prompt_after_the_ai_click`.

**Update (2026-10-05, second fix): the optional AI detour no longer fails the run.**
- Real run: after "Try AI job search" LinkedIn switched to
  `.../jobs/search-results/?origin=SEMANTIC_SEARCH_MODE_FROM_CLASSIC` with **no
  `keywords`** and rendered **zero job cards**; the repeat search returned no
  results and Task 2 then found `0 job(s)` and the run failed.
- `_task1_on_page` now recovers: when the post-AI repeat search finds no job
  list, `restore_job_search` navigates to the standard jobs search URL
  (`build_jobs_search_url`) and waits for results, and the note records
  "restored the standard job search". A repeat search that succeeds still never
  navigates (existing no-reload test unchanged).
- Evidence: new unit test
  `test_run_task1_recovers_when_the_ai_search_leaves_no_jobs`; the new
  `restore_job_search` helper in `src/tools/browser.py`. Full suite
  `uv run pytest` → 173 passed, 6 skipped; `uv run ruff check .` → clean.

Unit tests: `uv run pytest` → 171 passed, 6 skipped (or 173 passed, 4 skipped with
`AUTOJOB_TASK1_LIVE=1` to include the live-browser tests); `uv run ruff check .` →
clean; `uv run autojob --dry-run` → exit 0.

**Update (2026-10-05, third fix): removed the "no page reload" requirement.**
- "No page reload" is **not** LinkedIn's default behaviour: submitting the jobs
  search normally reloads/navigates. The requirement was removed from Task 1's
  spec, code, and tests so searching follows LinkedIn's normal behaviour.
- `type_jobs_search` / `open_jobs_search` no longer take `open_jobs_tab` /
  `allow_navigation`; the repeat search after the optional AI click is a normal
  search too and may reload/navigate. `restore_job_search` still recovers a job
  list when the optional AI detour leaves none.
- Removed the no-reload unit test and the `sessionStorage.loads`-based no-reload
  assertions from the live Task 1 test; `task/task.md` no longer claims searching
  avoids a reload.
- Evidence: `uv run pytest` → 172 passed, 6 skipped; `uv run ruff check .` →
  clean; `uv run autojob --dry-run` → exit 0.

**Update (2026-10-05, fourth fix): removed the AI-detour recovery.**
- The Task 1 spec dropped the "The AI detour is never fatal" note: the optional
  "Try AI job search" detour is **not** recovered, because searching follows
  LinkedIn's normal behaviour.
- `_task1_on_page` no longer calls a recovery search. When the post-AI repeat
  search returns no results the re-click loop simply stops and the outcome
  reflects the empty repeat (`results_found=False`, `results_count=0`), so the
  run reports "job search returned no results" instead of silently recovering.
- Deleted the now-unused `restore_job_search` helper from `src/tools/browser.py`.
- Also trimmed the redundant "Open the jobs tab first only if the search bar is
  not already on the page" sentence from Task 1 step 7; the Notes still document
  that the Jobs tab is opened only when the search bar is absent.
- Evidence: replaced the recovery unit test with
  `test_run_task1_stops_when_repeat_search_returns_no_results`; `uv run pytest` →
  172 passed, 6 skipped; `uv run ruff check .` → clean;
  `uv run autojob --dry-run` → exit 0.

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

## Task 3 — Read the job description and pick the best-matching resume

**Status:** ✅ Done
**Completed:** 2026-10-04

**What was done**
- Reads the open job's title, company, location, and description body from the
  details pane (same browser session as Tasks 1-2).
- Lists every resume in `resumes/` (`.pdf`, `.docx`, `.txt`, `.md`) and extracts
  readable text (pypdf for PDFs; stdlib zip/XML for `.docx`).
- Scores each resume against the job description with an explainable weighted
  match (shared skills, title overlap, seniority, years of experience) and
  selects the highest scorer.
- Records the chosen resume path and the matching rationale; ties go to the most
  recently modified file. Resume files are never modified.

**Evidence**
- `src/tools/browser.py` — `read_job_description` (Task 3 read step).
- `src/tools/matching.py` — `score_resume` (pure, explainable scoring).
- `src/tools/resumes.py` — `list_resume_files`, `extract_resume_text`,
  `select_best_resume`.
- `src/nodes/match.py` — the offline selection node; `src/nodes/verify.py` —
  `_task3_succeeded`.
- Unit tests: `tests/unit/test_matching.py`, `tests/unit/test_resumes.py`,
  `tests/unit/test_graph.py`, `tests/unit/test_browser_tools.py`.
- Integration: `tests/integration/test_resume_selection.py` (real PDFs).
- Validated against the three real resumes in `resumes/`: a "Senior Python
  Backend Engineer" description selected `ShaktiKC_Resume_python_Node_Senior.pdf`,
  and an "Agentic AI / LLM Engineer" description selected
  `Shakti_KC_Resume_AgenticAI (1).pdf`.

---

## Task 4 — Open Easy Apply and start filling the application form

**Status:** ✅ Done
**Completed:** 2026-10-04

**What was done**
- Enumerates the open Easy Apply form's controls (text, textarea, select, radio,
  checkbox) with their labels.
- Fills every field whose question is in the answer store (`data/answers.json`);
  unknown questions are recorded and left for Task 5.
- Treats the form as **dynamic**: discovers each step's fields, the resume
  control (radio list, `<select>`, file input, or an "Upload resume" button that
  reveals one), and the navigation buttons at runtime. The matching listed resume
  is selected directly; the file is only uploaded (over CDP `setFileInputFiles`)
  when nothing listed matches.
- Walks the steps until the terminal one, stopping gracefully if a step does not
  advance, and never clicking **Submit application**.
- Tasks 2-4 share one live browser session via an opaque `browser_run_id` (a
  `cleanup` node always closes it), so the gained Easy Apply modal is filled
  in-place without re-opening it.

**Evidence**
- `src/tools/answers.py` — the question → answer store (`load_answers`,
  `save_answer`, `lookup_answer`).
- `src/tools/forms.py` — `pick_listed_resume`, `looks_like_submit`/`looks_like_next`,
  `answers_match`, `looks_like_resume_field`.
- `src/tools/browser.py` — `_task4_on_page`, `_fill_step`, `_attach_resume`,
  `upload_file_via_cdp`, `start_tasks` / `fill_application` / `close_run`.
- `src/nodes/fill.py`, `src/nodes/cleanup.py`; `src/nodes/verify.py` —
  `_task4_succeeded`.
- Tests: `tests/unit/test_answers.py`, `tests/unit/test_forms.py`,
  `tests/unit/test_browser_tools.py`, `tests/unit/test_graph.py`.
- Live browser test: `tests/integration/test_fill_form_live.py` drives the real
  `_task4_on_page` against a local two-step Easy Apply fixture in real Chromium
  (opt-in via `AUTOJOB_FILL_LIVE=1`): known fields filled, the listed resume
  selected with no upload, a non-listed resume uploaded (`files == 1`), one step
  advanced, and Submit never clicked. Runnable in slow motion with
  `AUTOJOB_SESSION_HEADLESS=false` and `AUTOJOB_FILL_TEST_STEP_DELAY=1.5`.

---

## Task 5 — Ask the human for unknown answers, remember them, and show UI feedback

**Status:** ✅ Done
**Completed:** 2026-10-04

**What was done**
- The Task 4 fill now detects a question the answer store cannot answer and, when
  `AUTOJOB_SESSION_ASK_HUMAN` is on (default), **pauses** the run instead of
  guessing.
- A visible banner is injected into the browser window ("AutoJobApply does not
  know this answer") with the question, a text box, **Use answer**, and **Skip**;
  the run polls the banner until the human answers, skips, or the wait times out.
- The human's answer is filled (text/select/checkbox/radio, matching the right
  option), then saved to `data/answers.json` under the normalized question key, so
  the same question is answered automatically on later steps and later runs.
- Unknown radio groups that a stored answer cannot satisfy are re-asked, and the
  changed mapping is recorded explicitly ("updated the stored answer …").
- The answer store is updated in memory as well as on disk, so a repeated question
  within the same run is filled with no second prompt. Answers the human skips or
  leaves blank stay flagged as unknown.
- **Fix (found in a real LinkedIn run):** controls the form has already filled are
  no longer treated as unknown. LinkedIn pre-fills its *Email address* and *Phone
  country code* `<select>`s from the profile, and the agent used to pause on them
  (and could not set the select from free text). Now a pre-filled select/radio/
  text control is accepted as-is (no prompt, no overwrite), a `<select>` answer is
  matched to the option's value by its visible text as well as its value, and the
  banner shows the allowed choices so the human can pick one.
- **Fix (accidental skips):** clicking **Use answer** with an empty box no longer
  silently marks the question skipped; the banner stays open and re-prompts (the
  **Skip** button is still there for an intentional skip).
- **Fix (noisy shutdown):** the harmless Windows `asyncio` "I/O operation on
  closed pipe" unraisable traceback printed after a run is now filtered by the
  CLI, so a successful run ends with clean output.
- **Fix (interrupted-run browser leftovers):** an interrupted run can leave a
  Chromium owning `data/profile`; a new launch then hands its command line to that
  instance and exits before opening its own CDP port ("Browser process … exited
  before CDP became available"). `build_browser` now detects a locked profile,
  closes only the browser processes whose command line references our dedicated
  profile, and clears the single-instance lock files before launching. A manual
  `uv run autojob --clean-profile` does the same on demand.
- Task 5 runs inside the Task 4 fill (no new graph node); the outcome is recorded
  in a new `Task5Outcome` (`asked` / `answered` / `skipped` / `timed_out` /
  `answered_questions`) on `AgentOutcome.task5` and `ApplyState.task5`, surfaced in
  the CLI summary and checked by `verify` (`_task5_succeeded`). The application is
  still never submitted.

**Evidence**
- `src/tools/browser.py` — `ask_human_for_answer`, `_remember_answer`, the
  `_SHOW_UNKNOWN_JS` / `_READ_UNKNOWN_JS` / `_HIDE_UNKNOWN_JS` banner, and the
  Task 5 wiring in `_fill_step` / `_task4_on_page` / `fill_application`.
- `src/state.py` — `Task5Outcome`, `FormField.answered_by`, `AgentOutcome.task5`.
- `src/configuration.py` — `ask_human`, `ask_timeout_seconds`, `ask_poll_seconds`
  (`AUTOJOB_SESSION_ASK_*`).
- `src/nodes/fill.py` — stores `task5`; `src/nodes/verify.py` — `_task5_succeeded`;
  `src/main.py` — the human-help summary lines and the `--clean-profile` command.
- `src/tools/browser.py` — `terminate_profile_browsers` / `clear`-profile lock
  helpers used by `build_browser`; `src/configuration.py` —
  `clean_stale_profile` (`AUTOJOB_SESSION_CLEAN_STALE_PROFILE`).
- Tests: `tests/unit/test_browser_tools.py` (asks once and reuses the stored
  answer, skip, disabled, radio group, **pre-filled control skipped**, **select
  label mapped to option value**), `tests/unit/test_configuration.py`,
  `tests/unit/test_graph.py` (fill node propagation + verify gate).
- Live browser test: `tests/integration/test_fill_form_live.py::test_task5_pauses_for_the_human_and_remembers`
  drives real Chromium: the banner appears ("does not know" + the question), the
  test types the answer and submits it, the field is filled, the banner is removed,
  and the answer is persisted to the store. (`AUTOJOB_FILL_LIVE=1`)
- `uv run pytest` → 133 passed, 4 skipped; `uv run ruff check .` → clean;
  `uv run autojob --dry-run` → exit 0.

**Update (2026-10-05): fixed a live-browser kill that broke CDP.**
- `build_browser`'s stale-profile recovery keyed off `_profile_is_locked`, which on
  Windows is true for a **live** browser (Chromium holds `lockfile` while it runs).
  It then ran `terminate_profile_browsers` (`taskkill /F /T`), force-closing a
  browser that another run was driving. That run's CDP WebSocket dropped and every
  reconnect failed: `🔌 CDP WebSocket message handler exited unexpectedly
  (connection closed)` → `ConnectionRefusedError: [WinError 1225]`.
- Recovery now separates a **stale** lock from a **live** owner: it clears the lock
  files only when no process references the profile, and otherwise raises a clear
  "another browser is already using the AutoJobApply profile" error without killing
  anything. `terminate_profile_browsers` is now used only by the explicit
  `autojob --clean-profile`.
- Evidence: reproduced the exact drop (a second `build_browser` killed the first
  session; the profile's `Default/Preferences` then showed `exit_type: Crashed`) and
  verified the fix (the second launch raises `RuntimeError` and the first session's
  `is_cdp_connected` stays `True`). Regression test
  `test_build_browser_refuses_to_kill_a_live_browser_holding_the_profile`; full test
  suite + `ruff check .` clean.

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
