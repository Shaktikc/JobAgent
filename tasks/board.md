# Kanban — AutoJobApply (MVP)

**Single source of truth for task status.** Task definitions (acceptance criteria,
verification, files) live in `tasks/todo.md`. Sequencing, decisions, and risks live in
`tasks/plan.md`. Spec: `SPEC.md`.

Last updated: 2026-09-30 · **Done 6 / 16 tasks** · WIP limit: 1

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

- **T7** — `filling`: single-step fields, resume upload, screenshots *(Phase 1, dep: T3, T6)*
- **T8** — `review-gate` + minimal graph + `run --url <job> --dry-run` *(Phase 1, dep: T2, T7)*
- **T9** — LLM client (OpenRouter) with structured output *(Phase 2, dep: T1)*
- **T10** — `answering`: LLM integration + `NEEDS_REVIEW` threshold *(Phase 2, dep: T6, T9)*
- **T11** — `routing`: resume auto-index + selection *(Phase 2, dep: T2, T9)*
- **T12** — `discovery`: search, filters, dedupe *(Phase 2, dep: T5, T4, T2)*
- **T13** — `filling`: multi-step navigation *(Phase 3, dep: T7)*
- **T14** — `filling`: widgets + unknown handling *(Phase 3, dep: T13)*
- **T15** — `orchestration`: run loop, checkpointing, crash resume, `status` *(Phase 3, dep: T2–T14)*
- **T16** — Guarded live validation, 5–10/day *(Phase 4, dep: CP-D)*

## 🟡 In Progress

*(none)*

## 🔴 Blocked

*(none)*

## 🟣 Review (awaiting human inspection)

*(none)*

## 🟢 Done

- **T1** — Project scaffold, tooling, config templates, placeholder stubs *(Phase 0)*
  - Verified 2026-09-29: `poetry install` → 0 · `poetry check` → All set · ruff → clean ·
    mypy → 23 files clean · pytest → 10 passed · `python -m src.main --help` → 0 ·
    placeholders AST-verified as docstring-only · Chromium downloaded.
- **T2** — `state`: SQLite schema + repository (`tools/store.py`) *(Phase 0)*
  - Recovered 2026-09-30 from lost uncommitted work, via the compiled `.pyc` bytecode
    (source, tests, and schema were reconstructed; the original compiled test module
    passes 16/16 against the reconstruction). Two style-only lint fixes applied
    (`str, Enum` → `StrEnum`; combined nested `with`).
  - Verified 2026-09-30: `pytest -m "not integration"` → 26 passed (16 in
    `test_store.py`) · `ruff check .` → clean · `mypy src` → 23 files clean ·
    schema creates `jobs`, `answers`, `resume_index` idempotently with the six status
    and four provenance `CHECK` values.
- **T3** — `session`: browser launch, persistent profile, `login` *(Phase 0)*
  - Implemented 2026-09-30: `tools/browser.py` (only browser entry point + `login`),
    `tools/linkedin.py` (login-state predicate), `SessionSettings`/`Viewport` in
    `configuration.py`, `login` wired in `main.py`.
  - Verified 2026-09-30: `pytest -m "not integration"` → 37 passed (11 in
    `test_session_config.py`) · `pytest -m integration tests/integration/test_session_browser.py`
    → 2 passed (real Chromium: configured UA/viewport, cookies survive a restart) ·
    `ruff check .` clean · `mypy src` clean.
  - Criterion 1 (login persists; a second run reuses it) signed off by the owner on
    2026-09-30.
- **T4** — `guard`: pacing, daily cap, business hours, STOP sentinel *(Phase 0)*
  - Implemented 2026-09-30: `tools/guard.py` (`Guard`, `GuardHalt`,
    `detect_rate_limit_signal`) with injectable clock/sleep/rng; STOP sentinel;
    daily cap via `store.count_applied_today`; business-hours gate; randomized
    20–90s pacing; a rate-limit/checkpoint signal trips STOP and raises.
  - Verified 2026-09-30: `pytest -m "not integration" tests/unit/test_guard.py`
    → 19 passed (fake clock) · full suite → 56 passed · `ruff check .` clean ·
    `mypy src` clean · manual: created `data/STOP`, next guarded action raised
    `GuardHalt`, sentinel removed.
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

**CP-B — Riskiest assumption proven ⚠️** *(after T5–T8)* · status: Backlog
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
