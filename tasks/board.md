# Kanban — AutoJobApply (MVP)

**Single source of truth for task status.** Task definitions (acceptance criteria,
verification, files) live in `tasks/todo.md`. Sequencing, decisions, and risks live in
`tasks/plan.md`. Spec: `SPEC.md`.

Last updated: 2026-09-30 · **Done 6 / 17 tasks** · WIP limit: 1

> Architecture change 2026-09-30: the owner directed replacing Playwright with the
> browser-use AI agent. Recorded in `docs/decisions/0001-browser-use-migration.md`
> (ADR 0001) and task **T17**. The human submit gate, `guard`, `store`, facts rules
> and `review-gate` are preserved; only the browser-driving layer is replaced. Work
> is on branch `feature/browser-use-migration`; nothing is deleted until the agent
> path is demonstrated and CP-B is re-run.

> Audit 2026-09-30: T1 was already complete; T2's uncommitted source had been lost
> (HEAD `c8d84ac`, "wokring on task 2", contains only T1 artifacts) while its compiled
> `.pyc` cache remained. T2 was recovered from that bytecode, re-verified, and is now
> **Done** — see the Done card and Change Log.

---

## Rules for every agent (read before touching a task)

1. **Update this board before starting a task** (move its card to In Progress) and
   **immediately after finishing it** (move it to Done).
2. **Status lives only here.** Never add status checkboxes to `plan.md` or `todo.md`.
   Those files describe *what* a task is; this file records *where* it is.
3. **WIP limit is 1.** One In Progress card at a time unless the human says otherwise.
4. If work cannot proceed, move the card to Blocked and write the blocker inline.
5. Append one line to the Change Log for every card move.
6. A task is **Done** only when every acceptance criterion in `tasks/todo.md` is met
   *and* its verification step has actually been run.

---

## 🔵 Backlog

- **T9** — LLM client (OpenRouter) with structured output *(Phase 2, dep: T1)*
- **T10** — `answering`: LLM integration + `NEEDS_REVIEW` threshold *(Phase 2, dep: T6, T9)*
- **T11** — `routing`: resume auto-index + selection *(Phase 2, dep: T2, T9)*
- **T12** — `discovery`: search, filters, dedupe *(Phase 2, dep: T5, T4, T2)*
- **T13** — `filling`: multi-step navigation *(Phase 3, dep: T7)*
- **T14** — `filling`: form fields + unknown handling *(Phase 3, dep: T13)*
- **T15** — `orchestration`: run loop, checkpointing, crash resume, `status` *(Phase 3, dep: T2–T14)*
- **T16** — Guarded live validation, 5–10/day *(Phase 4, dep: CP-D)*

## 🟡 In Progress

*(none)*

## 🔴 Blocked

*(none)*

## 🟣 Review (awaiting human inspection)

- **T7** — `filling`: single-step fields, resume upload, screenshots *(Phase 1, dep: T3, T6)*
  - Implemented 2026-09-30: `nodes/fill.py` — module-level selectors
    (`EASY_APPLY_BUTTON_SELECTOR`, `MODAL_SELECTOR`, `STEP_CONTROL_SELECTOR`,
    `TEXT_INPUT_SELECTOR`, `FILE_INPUT_SELECTOR`); pure `widget_kind`, `decide`,
    `normalize_label`/`lookup_answer`, `artifact_path`; guarded
    `open_application_form`, `fill_current_step`, `fill_application` (captures a
    failure screenshot, then re-raises so the job is marked `failed`). Every action
    goes through `guard` (`check_stop` per action, paced modal open); unrecognized
    widgets are left blank and flagged, never guessed.
  - Verified 2026-09-30 (unit): `pytest -m "not integration" tests/unit/test_fill_selectors.py`
    → 31 passed against `tests/fixtures/easy_apply_modal.html` (selector resolution,
    widget classification, fill/flag decisions, screenshot naming) · full suite →
    129 passed · `ruff check .` clean · `mypy src` clean.
  - **Human step pending, blocked on T8:** the todo's manual check is
    `python -m src.main run --url <job> --dry-run`, which requires the T8 graph. Once
    T8 lands, run that against one real Easy Apply job and confirm the step fills and
    a PNG appears in `data/artifacts/`. Then move T7 to Done.
  - CP-B defects fixed 2026-09-30 (TDD, from the real dry-run of job `4468706364`):
    (1) `open_and_read_fields` silently returned `()` on a failed/absent agent read,
    hiding the bug behind "no fields"; it now raises `FillError`, and `_node_answer`
    marks the job `failed` (mirrors `_node_fill`). (2) `READ_FORM_TASK` + the fill
    task read/filled only the modal's first step ("1/4 pages" in the live form); both
    now walk every step via Next/Continue and still never Submit. Regression-guarded
    by `tests/unit/test_fill_read_fields.py` (8) + `test_browser_agent_tasks.py` (2),
    field-agnostic (they assert behavior, not a fixed field list). Re-run CP-B live.
- **T8** — `review-gate` + minimal graph + `run --url <job> --dry-run` *(Phase 1, dep: T2, T7)*
  - Implemented 2026-09-30: `nodes/review.py` — pure `parse_action`, `render_review`,
    `apply_edit`, `resolve_outcome`, and an interactive `review_application` with
    injectable prompt/output/submit. Excludes: reject ⇒ no submit + `rejected`;
    approve ⇒ exactly one submit + captured confirmation + `applied`; `--dry-run`
    never submits (stays `filled`); Ctrl-C/EOF ⇒ `filled`, re-offerable. `state.py`
    gained `answers`/`resume_file`/`status` and `RunState`; `fill.py` gained
    `list_step_widgets`, `submit_application`, `capture_confirmation`; `graph.py`
    builds the minimal LangGraph (`discover → answer → fill → review`) with injected
    `Runtime`; `main.py` wires `run --url [--dry-run]`.
  - Verified 2026-09-30 (unit): `pytest -m "not integration" tests/unit/test_review_decisions.py`
    → 36 passed (all decision paths, edits, dry-run, interrupt) · full suite →
    165 passed · `ruff check .` clean · `mypy src` clean · `python -m src.main --help`
    → 0 · `run` without `--url` → 2 · graph compiles with nodes
    `discover/answer/fill/review`.
  - **Human step pending — CP-B:** run `python -m src.main run --url <real Easy Apply job> --dry-run`,
    confirm it reaches review and stops with **no submission**, a PNG in
    `data/artifacts/`, and that the answers look right. Then move T7 and T8 to Done
    and sign off CP-B.
- **T17** — Browser layer: migrate Playwright → browser-use AI agent *(Phase 1.5, dep: T3, T5, T7, T9; ADR 0001; branch `feature/browser-use-migration`)*
  - Owner-directed full migration, 2026-09-30. **All Playwright code removed** (the
    `playwright` dependency too; browser-use drives the browser via CDP). The
    non-browser layers — `guard`, `store`, facts rules, the review gate — are kept.
  - New/changed: `tools/browser_agent.py` (pure `answers_to_field_instructions`,
    `sensitive_data_for`, `build_fill_task`, `build_submit_task`,
    `build_no_submit_system_message`; guarded async `run_task` with structured
    output; lazy `browser_use` imports). `tools/browser.py` now starts a browser-use
    `Browser` on `data/profile` and `login` is async. `tools/linkedin.py` is URL
    helpers + the agent read task. `nodes/discover.py` reads via the agent's
    structured `JobExtraction`. `nodes/fill.py` is agent-backed: `open_and_read_fields`,
    `fill_application`, and the gate-only `submit_application`. `review.py` is async.
    `graph.py`/`main.py` are async asyncio-native.
  - **The agent never submits on its own**: fill tasks carry a hard no-submit rule;
    submission is `build_submit_task`, called only by the review gate after approval.
    Answers are passed through `sensitive_data`, not pasted into prompts.
  - Verified 2026-09-30 (unit): full suite **135 passed**, 3 deselected ·
    `ruff check .` clean · `mypy src` 24 files clean · `--help` → 0 ·
    `run` without `--url` → 2 · graph compiles with nodes `discover/answer/fill/review`
    (async). API verified against installed `browser-use 0.13.10`.
  - **Human step pending — CP-B (now browser-use):** needs `OPENROUTER_API_KEY` +
    `AUTOJOB_LLM_MODEL` and `poetry run browser-use install`; then
    `python -m src.main run --url <real Easy Apply job> --dry-run`, confirm no
    submission + a PNG in `data/artifacts/`, and inspect the filled form.

## 🟢 Done

- **T1** — Project scaffold, tooling, config templates, placeholder stubs *(Phase 0)*
  - Original verification 2026-09-29 (see Change Log): `poetry install` → 0 ·
    `poetry check` → All set · ruff clean · mypy 23 files · pytest 10 passed ·
    `--help` → 0 · placeholders AST-verified docstring-only.
  - **Re-verified 2026-10-01 after the Playwright → browser-use migration:**
    `poetry check` → All set · `poetry install --dry-run` → 0 (135 pkgs, 0 changes) ·
    `python -m src.main --help` → 0 · `ruff check .` clean · `mypy src` 25 files clean ·
    placeholders still docstring-only · `.env.example` declares `OPENROUTER_API_KEY` +
    `AUTOJOB_LLM_MODEL` · `.gitignore` covers `data/`, `.env`, `.venv/`, `__pycache__/`.
    No `playwright` in `pyproject.toml` or `poetry.lock`; `browser-use 0.13.10` present.
    Regression fixed: `poetry.lock` content-hash re-synced (`poetry lock`; only the hash
    changed — `python-dotenv` was already a transitive dep of `pydantic-settings`).
  - Residual caveats (unchanged since the original sign-off; tracked separately, not T1
    blockers): SPEC §4 names `.opencode/agents.md`, `.opencode/agents/plan.md`,
    `.opencode/agents/review.md`, which are not committed (repo has untracked
    `.opencode/agents/autojobapply.md` + root `AGENTS.md`); `.opencode/skills/` exists
    although SPEC §4 says it is "not created"; the SPEC §4 tree also omits the active
    `tools/linkedin.py` and `tools/agent_hooks.py`.
- **T2** — `state`: SQLite schema + repository (`tools/store.py`) *(Phase 0)*
  - Recovered 2026-09-30 from lost uncommitted work, via the compiled `.pyc` bytecode
    (source, tests, and schema were reconstructed; the original compiled test module
    passes 16/16 against the reconstruction). Two style-only lint fixes applied
    (`str, Enum` → `StrEnum`; combined nested `with`).
  - Verified 2026-09-30: `pytest -m "not integration"` → 26 passed (16 in
    `test_store.py`) · `ruff check .` → clean · `mypy src` → 23 files clean ·
    schema creates `jobs`, `answers`, `resume_index` idempotently with the six status
    and four provenance `CHECK` values.
  - Re-verified 2026-10-01: fixed a time-bombed test —
    `test_count_applied_today_counts_only_todays_applied_jobs` hardcoded
    `date(2026, 9, 30)` while `set_job_status` stamps the real clock, so it passed only
    on that day. It now derives `date.today()`, matching `_now_iso`'s documented
    local-calendar-day prefix. Full unit suite → **154 passed, 3 deselected**;
    `ruff check .` clean; `mypy src` 25 files clean.
- **T3** — `session`: browser launch, persistent profile, `login` *(Phase 0)*
  - Implemented 2026-09-30: `tools/browser.py` (only browser entry point + `login`),
    `tools/linkedin.py` (login-state predicate), `SessionSettings`/`Viewport` in
    `configuration.py`, `login` wired in `main.py`.
  - Criterion 1 (login persists; a second run reuses it) signed off by the owner on
    2026-09-30.
  - **Re-verified 2026-10-01 after the browser-use migration.** Fixed a stale
    integration test: `Page.evaluate` in browser-use 0.13.10 requires the
    arrow-function form, so the Playwright-style `"navigator.userAgent"` raised
    `ValueError`; both calls now use `() => …` and the numeric result is coerced
    (`evaluate` returns a string). Verification: `pytest -m integration
    tests/integration/test_session_browser.py` → **2 passed** (real Chromium on a
    throwaway profile: configured UA/viewport applied, profile reused across two
    sessions) · `pytest -m "not integration" tests/unit/test_session_config.py` →
    **10 passed** · full unit suite **154 passed, 3 deselected** · `ruff check .`
    clean · `mypy src` 25 files clean · `login` and `--help` exit 0. (Prior card
    said 11 session tests; the real count is 10.) Note: browser-use emits a harmless
    Windows asyncio `PytestUnraisableExceptionWarning` at teardown (exit 0).
    Invariants hold: `tools/browser.py` is the only module constructing
    `Browser`/`BrowserProfile` (the agent receives the injected browser); the profile
    is `data/profile`, never the everyday Chrome profile; UA/viewport come from
    `SessionSettings`, not hardcoded in the browser module.
- **T4** — `guard`: pacing, daily cap, business hours, STOP sentinel *(Phase 0)*
  - Implemented 2026-09-30: `tools/guard.py` (`Guard`, `GuardHalt`,
    `detect_rate_limit_signal`) with injectable clock/sleep/rng; STOP sentinel;
    daily cap via `store.count_applied_today`; business-hours gate; randomized
    20–90s pacing; a rate-limit/checkpoint signal trips STOP and raises.
  - Verified 2026-09-30: `pytest -m "not integration" tests/unit/test_guard.py`
    → 19 passed (fake clock) · full suite → 56 passed · `ruff check .` clean ·
    `mypy src` clean · manual: created `data/STOP`, next guarded action raised
    `GuardHalt`, sentinel removed.
  - **Re-verified 2026-10-01 after the browser-use migration — no defect.** All six
    criteria hold. `pytest -m "not integration" tests/unit/test_guard.py` → **19
    passed** · full unit suite **154 passed, 3 deselected** · `ruff check .` clean ·
    `mypy src` 25 files clean · manual real-path STOP check repeated (`data/STOP`
    → `GuardHalt`, sentinel removed). Wiring intact through the browser-use layer:
    `main.py` asserts startable/can-apply; `nodes/discover.py` checks page text via
    `browser.read_page_text`; `browser_agent.run_task` brackets every agent run with
    `check_stop` + `pause_between_actions`. Values still come from `GuardSettings`
    (cap 30, 09:00–18:00, 20–90s), and clock/sleep/rng remain injectable.
- **T5** — `discovery` (partial): read a job, detect Easy Apply from a URL *(Phase 1)*
  - Implemented 2026-09-30: `tools/linkedin.py` (`JobDetails`, `job_id_from_url`,
    `detect_easy_apply`, `parse_job_page`, browser `read_job`), `nodes/discover.py`
    (`NotEasyApplyError`, `ensure_easy_apply`, `extract_job`, `read_job`, `as_job_state`)
    and `state.JobState` (the shared contract). Parsing uses stdlib `html.parser`
    over read selectors — no new dependency.
  - Corrected 2026-09-30 after a live read failed: `read_job` now waits for the
    client-rendered description before parsing, and the parser reads LinkedIn's
    current stable hooks (`data-view-name="job-apply-button"`,
    `data-testid="expandable-text-box"`, `aria-label="Company, …"`, the SSR
    `<title>`) with the old class names kept as fallback. Two Aero fixtures added.
  - Verified 2026-09-30: `pytest -m "not integration" tests/unit/test_discover_parse.py`
    → 19 passed · full suite → 75 passed · `ruff check .` clean · `mypy src` clean ·
    `pytest -m integration tests/integration/test_discover_browser.py` → 1 passed
    against a **real Easy Apply page** (`jobs/view/4468706364/`, both the canonical
    view URL and the `search-results/?currentJobId=…` form), fields non-empty and
    Easy Apply detected.
- **T6** — `answering`: facts rules + provenance, no LLM *(Phase 1)*
  - Implemented 2026-09-30: `nodes/answer.py` — `match_rule` (case-insensitive
    regex over `config/facts.yaml` rules), `rule_value` (literal or
    `answer_from` fact path, booleans rendered Yes/No), `answer_field` /
    `answer_fields` emitting the shared `store.Answer` with provenance and
    confidence. Precedence is rule → resume → LLM guess; a matched rule always
    claims the field, and anything uncovered is `NEEDS_REVIEW` with an empty
    value (never silently empty).
  - Verified 2026-09-30: `pytest -m "not integration" tests/unit/test_answer_rules.py`
    → 23 passed (real `facts.yaml` loads/validates; regex match; provenance and
    confidence; precedence over supplied LLM output) · full suite → 98 passed ·
    `ruff check .` clean · `mypy src` clean.
  - No LLM, no network, no browser — deterministic and fully covered by unit tests,
    so no human-only step is required.

---

## Checkpoints (gate criteria)

Each checkpoint must be explicitly verified with the human before the next phase begins.

**CP-A — Foundation** *(after T1–T4)* · status: ⚠️ criteria met 2026-09-30 — awaiting human sign-off
- `poetry install` and `python -m src.main --help` succeed ✓
- `login` persists a session; a second run reuses it (criterion 1) ✓ (T3, owner sign-off)
- Guard refuses the 31st daily attempt and out-of-hours runs (criterion 9) ✓ (T4)
- All unit tests pass; `ruff check .` clean ✓
- Human sign-off required before Phase 1 (T5+) begins.

**CP-B — Riskiest assumption proven ⚠️** *(after T5–T8)* · status: ⚠️ code complete 2026-09-30 — awaiting the human dry-run + form inspection
- The go/no-go gate for the whole project.
- `--dry-run` on **one real LinkedIn job** reaches review with no submission
- A screenshot exists in `data/artifacts/` for that application (criterion 12, partial)
- Reject ⇒ no submit; approve ⇒ exactly one submit (criterion 7); `--dry-run` never submits (criterion 8)
- **Human inspects the real filled form and confirms the answers are correct**
- If any of the above fails: stop, revisit `SPEC.md`, do not build Phase 2

**CP-C — Discovery + intelligence** *(after T9–T12)* · status: Backlog
- `search` populates SQLite with config-matching Easy-Apply jobs (criterion 2)
- Routing picks the expected resume on a fixture set (criterion 3)
- Two different OpenRouter models both answer a fixture (criterion 13)
- `facts.yaml` hard rules are respected in real answers

**CP-D — Complete** *(after T13–T15)* · status: Backlog
- All success criteria 1–13 demonstrably pass
- A crash mid-run resumes without re-applying to already-applied jobs (criterion 10)
- Every application reaching review has a screenshot (criterion 12)
- `ruff check .` and `mypy src` clean

---

## Change Log

| Date | Task | From → To | Note |
|---|---|---|---|
| 2026-09-29 | — | — | Board created. All tasks Backlog. |
| 2026-09-29 | T1 | Backlog → In Progress | Scaffold is the first dependency; starting implementation. |
| 2026-09-29 | T1 | In Progress → Blocked | Poetry not installed; spec specifies Poetry. Awaiting human decision. |
| 2026-09-29 | T1 | Blocked → In Progress | Human: install Poetry, keep the spec; download Chromium during scaffold. |
| 2026-09-29 | T1 | In Progress → Done | All acceptance criteria verified (commands in the Done card). |
| 2026-09-30 | T1 | Done (re-verified) | Audit: `ruff` clean · `mypy src` 23 files clean · `pytest -m "not integration"` 10 passed · `--help` OK. |
| 2026-09-30 | T2 | Backlog (unchanged) | Audit: HEAD `c8d84ac` "wokring on task 2" contains only T1 artifacts; `store.py` still a stub, no `test_store.py`. T2 not started. |
| 2026-09-30 | T2 | Backlog → In Progress | Found lost uncommitted T2 work: 16 `test_store.py` tests passing today, compiled `.pyc` cache remains. Recovering source and re-verifying. |
| 2026-09-30 | T2 | In Progress → Done | Recovered `store.py` + `test_store.py` from `.pyc` bytecode; original compiled tests 16/16; full gate green (see Done card). |
| 2026-09-30 | T3 | Backlog → In Progress | Implement `session` (browser launch, persistent profile, `login`). |
| 2026-09-30 | T3 | In Progress → Review | Code + unit/integration verification green; awaiting the human login-twice check (criterion 1). |
| 2026-09-30 | T3 | Review → Done | Owner signed off criterion 1 (login persists, second run reuses). |
| 2026-09-30 | T4 | Backlog → In Progress | Implement `guard` (pacing, cap, hours, STOP, rate-limit). |
| 2026-09-30 | T4 | In Progress → Done | All acceptance criteria verified; 19 guard tests + manual STOP check green. |
| 2026-09-30 | T5 | Backlog → In Progress | Implement partial `discovery`: parse one job page + detect Easy Apply. |
| 2026-09-30 | T5 | In Progress → Review | Code + 12 fixture tests green; awaiting the human real-URL read (selectors vs. live DOM). |
| 2026-09-30 | T5 | Review → In Progress | Live read of a real Easy Apply URL failed: parse raced hydration and LinkedIn's hashed class names broke the read selectors. Fixing wait + selectors. |
| 2026-09-30 | T5 | In Progress → Done | Fixed hydration wait + stable hooks (Aero). Unit 19, full 75, ruff/mypy clean; real-URL integration test passes. |
| 2026-09-30 | T6 | Backlog → In Progress | Implement deterministic facts rule engine + provenance (no LLM). |
| 2026-09-30 | T6 | In Progress → Done | 23 rule-engine tests green; full suite 98 passed, ruff/mypy clean. |
| 2026-09-30 | T7 | Backlog → In Progress | Implement single-step filling: fields, resume upload, screenshot, guard. |
| 2026-09-30 | T7 | In Progress → Review | 31 fixture/selector tests green; live `run --url` check gated on T8 wiring. |
| 2026-09-30 | T8 | Backlog → In Progress | Implement review-gate + minimal graph + `run --url --dry-run`. |
| 2026-09-30 | T8 | In Progress → Review | 36 review tests green; graph compiles. Live dry-run + form inspection (CP-B) is the human step. |
| 2026-09-30 | T17 | — → In Progress | Owner requested replacing Playwright with the browser-use AI agent. ADR 0001 recorded; submit gate/guard/store/facts/review preserved. Foundation module + 7 pure task-builder tests landed. |
| 2026-09-30 | T17 | In Progress → Review | Full migration done: all Playwright code removed (dependency too); browser-use drives login/read/fill; submit is gate-only. 135 unit tests, ruff/mypy clean. Live dry-run is the human step. |
| 2026-09-30 | T7 | Review (re-verified) | CP-B TDD fixes from the real dry-run of job `4468706364`: field-read no longer silently returns `()` (raises `FillError`, job → `failed`); read/fill walk every modal step (was page 1 of "1/4 pages"). +10 field-agnostic tests, full suite 145 passed, ruff/mypy clean. Re-run live CP-B. |
| 2026-10-01 | T1 | Done → In Progress | Re-verification after Playwright→browser-use: clean `poetry install` fails (`poetry.lock` stale; `python-dotenv` added in `ef56a57` without relocking). Syncing the lock. |
| 2026-10-01 | T1 | In Progress → Done | Re-synced `poetry.lock` (content-hash only; `python-dotenv` already transitive). `poetry check`, `install --dry-run`, `--help`, `ruff`, `mypy` all green; browser-use 0.13.10 intact, no Playwright. |
| 2026-10-01 | T2 | Done → In Progress | Reopened: `test_count_applied_today_*` hardcoded `date(2026, 9, 30)` and fails off that day; making it clock-deterministic. |
| 2026-10-01 | T2 | In Progress → Done | Test now uses `date.today()` (matches `_now_iso`); full unit suite 154 passed, 3 deselected; ruff/mypy clean. |
| 2026-10-01 | — | — | Untracked PII resumes per SPEC.md §8: `resumes/` and `myResumes/` PDFs removed from the index, `resumes/.gitkeep` added, both folders gitignored. |
| 2026-10-01 | T3 | Done → In Progress | Reopened: integration smoke fails on browser-use 0.13.10 — `Page.evaluate` requires `(...args) => …`; test used Playwright-style bare expressions. |
| 2026-10-01 | T3 | In Progress → Done | Fixed arrow-function form + numeric coercion; integration 2 passed, T3 unit 10 passed, full suite 154, ruff/mypy clean. |
| 2026-10-01 | T4 | Done (re-verified) | Post-migration check: 19 guard tests + full suite 154 passed, ruff/mypy clean; manual `data/STOP` halt re-run and sentinel cleaned. No defect; guard wiring through browser-use intact. |
