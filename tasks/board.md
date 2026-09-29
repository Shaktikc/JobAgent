# Kanban — AutoJobApply (MVP)

**Single source of truth for task status.** Task definitions (acceptance criteria,
verification, files) live in `tasks/todo.md`. Sequencing, decisions, and risks live in
`tasks/plan.md`. Spec: `SPEC.md`.

Last updated: 2026-09-29 · **Done 1 / 16 tasks** · WIP limit: 1

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

- **T2** — `state`: SQLite schema + repository (`tools/store.py`) *(Phase 0, dep: T1)*
- **T3** — `session`: browser launch, persistent profile, `login` *(Phase 0, dep: T1)*
- **T4** — `guard`: pacing, daily cap, business hours, STOP sentinel *(Phase 0, dep: T1, T2)*
- **T5** — `discovery` (partial): read a job, detect Easy Apply from a URL *(Phase 1, dep: T3)*
- **T6** — `answering`: facts rules + provenance, no LLM *(Phase 1, dep: T1)*
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

---

## Checkpoints (gate criteria)

Each checkpoint must be explicitly verified with the human before the next phase begins.

**CP-A — Foundation** *(after T1–T4)* · status: Backlog
- `poetry install` and `python -m src.main --help` succeed
- `login` persists a session; a second run reuses it (criterion 1)
- Guard refuses the 31st daily attempt and out-of-hours runs (criterion 9)
- All unit tests pass; `ruff check .` clean

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
