# Task List: AutoJobApply (MVP)

Plan: `tasks/plan.md` · Spec: `SPEC.md` · **Status: `tasks/board.md` (single source of truth)**

Commands: `poetry run python -m src.main <cmd>`

This file defines *what* each task is (acceptance criteria, verification, files).
It does **not** track status — move cards on `tasks/board.md` instead.

Order is dependency order, and Phase 1 is deliberately the risk-first walking skeleton
(see plan.md Architecture Decision 1). Do not reorder Phase 1 after Phase 2.

---

## Task 1: Project scaffold, tooling, config templates, placeholder stubs

**Description:** Create the SPEC §4 directory tree, Poetry package config, LangGraph
blueprint, env template, gitignore entries, and the docstring-only template stubs.
Mechanically large (many empty files) but substantively small.

**Acceptance criteria:**
- [ ] `poetry install` succeeds on a clean checkout
- [ ] `python -m src.main --help` runs and exits 0
- [ ] Every path in SPEC §4 exists, including the marked placeholders
- [ ] `.env.example` declares `OPENROUTER_API_KEY` and `AUTOJOB_LLM_MODEL`
- [ ] `.gitignore` covers `data/`, `.env`, `.venv/`, `__pycache__/`
- [ ] Placeholders (`nodes/ingest|plan|execute|verify.py`, `tools/opencode_client.py`,
      `tools/git_snapshot.py`, `workspace/`) contain a docstring and nothing else

**Verification:**
- [ ] `poetry install && poetry run python -m src.main --help`
- [ ] `poetry run ruff check .` clean
- [ ] Manual: confirm no placeholder contains invented logic

**Dependencies:** None
**Files likely touched:** `pyproject.toml`, `langgraph.json`, `.env.example`, `.gitignore`,
`src/configuration.py` (+ generated stub/config templates)
**Estimated scope:** M (mechanical; ~5 substantive files)

---

## Task 2: `state` — SQLite schema and repository

**Description:** Persistence for `tools/store.py`: jobs, statuses, answers, resume index.
Distinct from `src/state.py` (LangGraph channels), which Task 8 introduces.

**Acceptance criteria:**
- [ ] Schema is created idempotently on first run
- [ ] Jobs dedupe by LinkedIn job id; re-seeing a job does not duplicate it
- [ ] Status values are exactly `seen | skipped | filled | rejected | applied | failed`
- [ ] Every answer row records field, value, provenance, confidence
- [ ] `count_applied_today()` is queryable and correct
- [ ] A killed process leaves no partial row (upsert is transactional)

**Verification:**
- [ ] `poetry run pytest -m "not integration" tests/unit/test_store.py`
- [ ] Manual: `sqlite3 data/autojobapply.db ".schema"`

**Dependencies:** Task 1
**Files likely touched:** `src/tools/store.py`, `src/configuration.py`,
`tests/unit/test_store.py`
**Estimated scope:** M

---

## Task 3: `session` — browser launch, persistent profile, `login`

**Description:** A browser-use `Browser` on a dedicated persistent profile, plus the
`login` command that waits for a manual LinkedIn login and persists the session.

**Acceptance criteria:**
- [ ] `login` opens a real browser on `data/profile`, navigates to LinkedIn, waits for
      manual login, and persists cookies
- [ ] A second `login` run reuses the session without prompting (criterion 1)
- [ ] The browser is launched **only** through this module
- [ ] The everyday Chrome profile is never touched
- [ ] User-agent/viewport come from `configuration.py`, not hardcoded

**Verification:**
- [ ] Manual: run `login` twice; second run shows a logged-in session
- [ ] `poetry run pytest -m "not integration" tests/unit/test_session_config.py`

**Dependencies:** Task 1
**Files likely touched:** `src/tools/browser.py`, `src/tools/linkedin.py`,
`src/main.py`, `src/configuration.py`, `tests/unit/test_session_config.py`
**Estimated scope:** M

---

## Task 4: `guard` — pacing, daily cap, business hours, STOP sentinel

**Description:** The safety envelope. Every network/browser action must pass through it.

**Acceptance criteria:**
- [ ] The 31st application attempt in a calendar day is refused with a clear message
- [ ] Runs outside 09:00–18:00 local refuse to start
- [ ] A randomized 20–90s delay is applied between actions
- [ ] If `data/STOP` exists, the next guarded action halts the run
- [ ] Clock and sleep are injectable so tests are instant and deterministic
- [ ] A rate-limit/checkpoint signal from LinkedIn stops the run immediately

**Verification:**
- [ ] `poetry run pytest -m "not integration" tests/unit/test_guard.py` (fake clock)
- [ ] Manual: create `data/STOP`, confirm the next action halts

**Dependencies:** Task 1, Task 2
**Files likely touched:** `src/tools/guard.py`, `tests/unit/test_guard.py`
**Estimated scope:** S

---

## Checkpoint A — Foundation

Criteria and status: `tasks/board.md` → **CP-A**.

---

## Task 5: `discovery` (partial) — read a job and detect Easy Apply

**Description:** Given one job URL, extract title/company/description/URL and detect
whether Easy Apply is available. Emits the `JobState` that later tasks consume.

**Acceptance criteria:**
- [ ] Title, company, description, and URL are read correctly for a real job page
- [ ] Easy Apply availability is detected before any filling is attempted
- [ ] A non-Easy-Apply job raises a clear, typed error rather than proceeding
- [ ] Job-id and login-state helpers are unit-testable with no network

**Verification:**
- [ ] `poetry run pytest -m "not integration" tests/unit/test_linkedin_agent.py`
- [ ] Manual: run against one real Easy Apply URL

**Dependencies:** Task 3
**Files likely touched:** `src/tools/linkedin.py`, `src/nodes/discover.py`,
`tests/unit/test_linkedin_agent.py`
**Estimated scope:** M

---

## Task 6: `answering` — facts rules and provenance (no LLM)

**Description:** Deterministic rule engine over `config/facts.yaml`, plus the `Answer`
type carrying provenance and confidence. LLM comes in Task 10.

**Acceptance criteria:**
- [ ] `facts.yaml` loads and validates; hard rules are matched by regex
- [ ] Every field yields exactly one `Answer(value, provenance, confidence)`
- [ ] Provenance is one of `RESUME | FACTS_RULE | LLM_GUESS | NEEDS_REVIEW`
- [ ] Fields no rule covers are marked `NEEDS_REVIEW` — never left silently empty
- [ ] Rules always take precedence over any future LLM output

**Verification:**
- [ ] `poetry run pytest -m "not integration" tests/unit/test_answer_rules.py`

**Dependencies:** Task 1
**Files likely touched:** `src/nodes/answer.py`, `tests/unit/test_answer_rules.py`
**Estimated scope:** S

---

## Task 7: `filling` — single-step fields, resume upload, screenshots

**Description:** Fill one Easy Apply modal step: text inputs, resume upload, and a
screenshot for every application. Multi-step navigation is Task 13.

**Acceptance criteria:**
- [ ] Text fields are filled with the values produced by Task 6
- [ ] The routed resume PDF is uploaded to the file input
- [ ] A PNG of the filled form is saved to `data/artifacts/` for **every** application
- [ ] Browser-use tasks are built as pure functions in `nodes/fill.py` and
      `tools/browser_agent.py`, never inline
- [ ] An unrecognized field is left blank and flagged, not guessed
- [ ] Every action is routed through `guard`

**Verification:**
- [ ] `poetry run pytest -m "not integration" tests/unit/test_fill_agent.py tests/unit/test_browser_agent_tasks.py`
- [ ] Manual: `run --url <job> --dry-run` fills a real form and stops at review

**Dependencies:** Task 3, Task 6
**Files likely touched:** `src/nodes/fill.py`, `src/tools/browser_agent.py`,
`tests/unit/test_fill_agent.py`, `tests/unit/test_browser_agent_tasks.py`
**Estimated scope:** M

---

## Task 8: `review-gate` + minimal graph + `run --url <job> --dry-run`

**Description:** The human checkpoint and the smallest LangGraph wiring that reaches it.
Requires an explicit `--url` so the skeleton needs no search yet.

**Acceptance criteria:**
- [ ] Review displays job title, company, URL, resume used, and every
      field/answer/provenance
- [ ] Accepts approve / reject / edit; an edit updates the value before submission
- [ ] Reject ⇒ zero submissions, `status=rejected`
- [ ] Approve (non-dry-run) ⇒ exactly one submission, confirmation captured,
      `status=applied`
- [ ] `--dry-run` never submits, regardless of approval
- [ ] Ctrl-C mid-review leaves the application `filled` and re-offerable

**Verification:**
- [ ] `poetry run pytest -m "not integration" tests/unit/test_review_decisions.py`
- [ ] Manual: full `--dry-run` on one real job reaches review and stops

**Dependencies:** Task 2, Task 7
**Files likely touched:** `src/nodes/review.py`, `src/graph.py`, `src/state.py`,
`src/main.py`, `tests/unit/test_review_decisions.py`
**Estimated scope:** M

---

## Checkpoint B — Riskiest Assumption Proven ⚠️

This is the gate that decides whether the project proceeds.
Criteria and status: `tasks/board.md` → **CP-B**.

---

## Task 9: LLM client (OpenRouter) with structured output

**Description:** One thin LLM wrapper: OpenRouter base URL, model from env, Pydantic-
validated structured responses, transient-error retry.

**Acceptance criteria:**
- [ ] Reads `OPENROUTER_API_KEY` and `AUTOJOB_LLM_MODEL` from the environment only
- [ ] Requests go to `https://openrouter.ai/api/v1`
- [ ] Responses are parsed into validated Pydantic objects — never regex over prose
- [ ] Changing `AUTOJOB_LLM_MODEL` changes the model with no code change
- [ ] Transient failures retry with backoff; permanent failures raise clearly

**Verification:**
- [ ] `poetry run pytest -m "not integration" tests/unit/test_llm_config.py`
- [ ] Manual: complete one fixture task with two different models (criterion 13)

**Dependencies:** Task 1
**Files likely touched:** `src/tools/llm.py`, `src/configuration.py`,
`tests/unit/test_llm_config.py`
**Estimated scope:** S

---

## Task 10: `answering` — LLM integration and `NEEDS_REVIEW` threshold

**Description:** Layer the LLM behind the Task 6 rules: rules first, LLM for the rest,
low-confidence results surfaced for human review.

**Acceptance criteria:**
- [ ] Rule matches short-circuit the LLM entirely
- [ ] LLM answers are schema-validated before use
- [ ] Answers below the confidence threshold become `NEEDS_REVIEW` and are left blank
- [ ] Provenance correctly distinguishes `RESUME`, `FACTS_RULE`, `LLM_GUESS`,
      `NEEDS_REVIEW`
- [ ] Resume text is never written to logs

**Verification:**
- [ ] `poetry run pytest -m "not integration" tests/unit/test_answer_llm.py` (stubbed LLM)
- [ ] Manual: one real OpenRouter call on a fixture form

**Dependencies:** Task 6, Task 9
**Files likely touched:** `src/nodes/answer.py`, `tests/unit/test_answer_llm.py`,
`tests/fixtures/`
**Estimated scope:** M

---

## Task 11: `routing` — resume auto-index and selection

**Description:** Index every PDF in `resumes/` (any number, any filename) by asking the
LLM for the roles it targets, cache by file hash, and pick the best match per job.

**Acceptance criteria:**
- [ ] Every PDF in `resumes/` is indexed regardless of count or filename
- [ ] Role keywords are LLM-extracted once per file hash and cached in SQLite
- [ ] Re-index triggers on file change or `reindex: true`
- [ ] `resumes.yaml` overrides win over the auto-extracted keywords
- [ ] A low-confidence match falls back to `default_variant` **and is flagged at review**
- [ ] No resume file is renamed or modified

**Verification:**
- [ ] `poetry run pytest -m "not integration" tests/unit/test_route.py` (fixture PDFs)
- [ ] Manual: index 3 differently-named real resumes and check the mapping

**Dependencies:** Task 2, Task 9
**Files likely touched:** `src/nodes/route.py`, `src/tools/resume_parser.py`,
`tests/unit/test_route.py`, `tests/fixtures/`
**Estimated scope:** M

---

## Task 12: `discovery` — search, filters, dedupe

**Description:** Complete `discovery`: run the search from `search.yaml`, harvest jobs,
apply filters, dedupe, and persist via `tools/store.py`.

**Acceptance criteria:**
- [ ] Search runs from `search.yaml` (keywords, location, remote, experience level)
- [ ] Only Easy Apply jobs are queued
- [ ] `posted_within_days` is enforced
- [ ] Only `exclude_keywords` / `exclude_companies` filter postings — no built-in
      heuristics, and "Promoted" listings are **not** excluded
- [ ] Duplicates are suppressed by job id; `max_results_per_run` is respected
- [ ] Every search action passes through `guard`

**Verification:**
- [ ] `poetry run pytest -m "not integration" tests/unit/test_discover_filters.py`
- [ ] Manual: `search` populates SQLite with matching jobs (criterion 2)

**Dependencies:** Task 5, Task 4, Task 2
**Files likely touched:** `src/nodes/discover.py`, `tests/unit/test_discover_filters.py`
**Estimated scope:** M

---

## Checkpoint C — Discovery + Intelligence

Criteria and status: `tasks/board.md` → **CP-C**.

---

## Task 13: `filling` — multi-step navigation

**Description:** Walk the Easy Apply modal through its Next/Review steps, handling
required starred fields and per-step validation.

**Acceptance criteria:**
- [ ] All steps advance until the final Submit is reached, without submitting
- [ ] Starred/required fields are filled; validation errors are not bypassed
- [ ] Progress state survives a retry of a failed step
- [ ] A hard failure captures a screenshot and marks the job `failed`

**Verification:**
- [ ] `poetry run pytest -m "not integration" tests/unit/test_fill_steps.py`
- [ ] Manual: `--dry-run` on a real multi-step job reaches the Submit button

**Dependencies:** Task 7
**Files likely touched:** `src/nodes/fill.py`, `tests/unit/test_fill_steps.py`
**Estimated scope:** M

---

## Task 14: `filling` — form fields and unknown handling

**Description:** Cover dropdowns, radio groups, checkboxes, and numeric fields via the
agent; define exactly what happens on an unrecognized required field.

**Acceptance criteria:**
- [ ] Dropdowns, radios, and checkboxes are set to the chosen answer
- [ ] Numeric/text-constrained fields validate before advancing
- [ ] An unrecognized required field is left blank and surfaced at review as
      `NEEDS_REVIEW` — never guessed, never a silent job skip
- [ ] Mixed-type multi-step forms fill correctly in one pass

**Verification:**
- [ ] `poetry run pytest -m "not integration" tests/unit/test_fill_agent.py`
- [ ] Manual: `--dry-run` on a job containing a dropdown and a radio group

**Dependencies:** Task 13
**Files likely touched:** `src/nodes/fill.py`, `src/tools/browser_agent.py`,
`tests/unit/test_fill_agent.py`
**Estimated scope:** M

---

## Task 15: `orchestration` — graph run loop, checkpointing, crash resume, `status`

**Description:** Wire the full loop per job and make it resumable: discovery → routing →
answering → filling → review-gate, until results are exhausted or guard halts.

**Acceptance criteria:**
- [ ] The loop processes jobs in order until exhaustion or a guard halt
- [ ] Every network/browser action in the loop routes through `guard`
- [ ] State is checkpointed so a restart resumes without re-applying (criterion 10)
- [ ] `status` reports counts by status (seen/applied/rejected/skipped/failed)
- [ ] A guard halt exits cleanly with a clear reason, leaving state consistent

**Verification:**
- [ ] `poetry run pytest -m "not integration"` (full unit suite)
- [ ] Manual: kill mid-run, restart, confirm no duplicate applications
- [ ] Manual: `status` output matches the database

**Dependencies:** Tasks 2–14
**Files likely touched:** `src/graph.py`, `src/state.py`, `src/main.py`,
`tests/unit/test_graph_resume.py`
**Estimated scope:** M

---

## Checkpoint D — Complete

Criteria and status: `tasks/board.md` → **CP-D**.

---

## Task 16: Guarded live validation (operational — no code)

**Description:** The real test of the product. Run against LinkedIn deliberately slowly
and measure the trust criterion before scaling.

**Acceptance criteria:**
- [ ] Run starts at **5–10 applications/day**, not 30, for the first week
- [ ] Zero wrong answers across the first 20 real applications (criterion 11)
- [ ] Take-over rate recorded: how often you finish a form in the browser instead
- [ ] Any account warning/restriction stops the run immediately (`data/STOP`)
- [ ] Cap is raised toward 30/day only after a clean week

**Verification:**
- [ ] Manual: review each application; log any answer you had to correct
- [ ] Review `data/artifacts/` screenshots against the review record

**Dependencies:** Checkpoint D
**Files likely touched:** none (config values only)
**Estimated scope:** M (calendar time, not code)

---

## Task 17: Browser layer — migrate Playwright → browser-use (AI agent)

**Description:** Owner-directed architecture change (see
`docs/decisions/0001-browser-use-migration.md`, ADR 0001). Replace the hand-written
Playwright browser layer with the browser-use agent. The browser-independent layers
(`guard`, `store`, facts rules, `review-gate`) are **kept unchanged**; only the code
that drives the browser is replaced. The human submit gate stays: the agent may read
and fill, never submit; submission is a separate agent task run only by the review
gate after approval.

**Acceptance criteria:**
- [ ] `tools/browser_agent.py`: pure task/answer builders + guarded agent runner;
      answers injected via `sensitive_data`, not embedded in prompt text
- [ ] `tools/browser.py`: browser-use `Browser` on the dedicated `data/profile`;
      manual login preserved; everyday Chrome profile never touched
- [ ] `nodes/fill.py`: agent-backed fill; `build_fill_task` carries a hard no-submit
      rule; submission is a gate-only task (`build_submit_task`)
- [ ] `nodes/discover.py` + `tools/linkedin.py`: job read via agent structured output,
      still emitting the same `JobState`
- [ ] Every agent run brackets `guard.check_stop()` and is paced; STOP halts it
- [ ] A PNG screenshot is still captured for every application
- [ ] No direct Playwright calls remain in the browser layer
- [ ] All prior browser-independent unit tests still pass

**Verification:**
- [ ] `poetry run ruff check .` and `poetry run mypy src` clean
- [ ] `poetry run pytest -m "not integration"` (full unit suite)
- [ ] Manual (owner, needs OpenRouter key + browser): `run --url <job> --dry-run`
      reaches review with **no submission** and a screenshot in `data/artifacts/`
- [ ] Manual: `login` persists via `data/profile`

**Dependencies:** Tasks 3, 5, 7 (browser layer); T9 for the LLM key
**Files likely touched:** `src/tools/browser_agent.py`, `src/tools/browser.py`,
`src/tools/linkedin.py`, `src/nodes/discover.py`, `src/nodes/fill.py`,
`src/graph.py`, `src/main.py`, `pyproject.toml`, `tests/unit/test_browser_agent_tasks.py`
**Estimated scope:** L
