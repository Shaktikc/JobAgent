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
