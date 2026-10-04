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
- Attaches the Task 3 resume: the matching resume already listed on the form is
  selected directly; the file is only uploaded (over CDP `setFileInputFiles`) when
  nothing listed matches.
- Advances multi-step forms (Next/Continue/Review) and stops before **Submit
  application**; Submit is never clicked.
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
