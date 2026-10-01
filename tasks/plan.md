# Implementation Plan: AutoJobApply (MVP)

Spec: `SPEC.md` (approved 2026-09-29). Idea: `docs/ideas/auto-job-apply.md`.
Tasks tracked in: `tasks/todo.md` (checklist markdown, default target).

## Overview

Build a single-user, local LangGraph agent that searches LinkedIn Easy Apply jobs,
auto-maps each job to one of your resumes, fills every form question, and pauses for
terminal review before submitting. Nine capability modules (`state`, `session`,
`guard`, `discovery`, `routing`, `answering`, `filling`, `review-gate`,
`orchestration`) map onto the template `src/nodes/` + `src/tools/` layout per SPEC §4.

## Architecture Decisions

1. **Risk-first walking skeleton.** SPEC's module build order starts at `state` and
   ends at `orchestration`, which would put the dealbreaker assumption (can this fill
   real Easy Apply forms at all?) at the *end*. This plan instead proves a thin
   vertical slice first — Tasks 5–8 drive a **single job URL** through read → answer →
   fill → review in `--dry-run` — and only then adds search, routing, and LLM
   sophistication. Same destination, riskiest assumption validated ~Task 8 instead of
   ~Task 15. This is the one deliberate deviation from the approved build order.
2. **Pattern:** `nodes/` hold thin, pure-ish graph functions over LangGraph state;
   *all* I/O (browser, DB, HTTP, PDFs) lives in `tools/`. This is what makes unit
   testing possible without a browser.
3. **Two different "states" never share a name:** `src/state.py` = LangGraph channels;
   `src/tools/store.py` = SQLite persistence.
4. **`NEEDS_REVIEW` is a first-class answer state, not an error.** Unknown required
   fields are left blank and surfaced — never guessed, never a silent job skip.
5. **OpenRouter via `langchain-openai`** with `base_url` override; model selected
   purely by `AUTOJOB_LLM_MODEL`, so swapping models is a config change, not code
   (success criterion 13).
6. **browser-use agent**, sequential, single job at a time. No parallelism — it is
   both simpler and safer for account risk.
7. **Template placeholders stay stubs.** `nodes/ingest|plan|execute|verify.py`,
   `tools/opencode_client.py`, `tools/git_snapshot.py`, `workspace/` are created as
   docstring-only files (owner decision) and must not receive invented behavior.
8. **Guard is not optional anywhere.** Every network/browser action routes through it;
   `data/STOP` halts within one step.
9. **Learned answers (owner request, added 2026-10-01).** When the agent is unsure of
   a form answer it asks the human, uses the reply, and stores it in SQLite
   (`learned_answers`), so a similar question later is answered from memory before
   asking again. Precedence: `FACTS_RULE` → `LEARNED` → `RESUME` → `LLM_GUESS` →
   `NEEDS_REVIEW`. Matching is **OpenRouter embeddings + cosine similarity** (owner
   decision), model from `AUTOJOB_EMBEDDING_MODEL`, routed through `guard`; an exact
   normalized match skips the embedding call. No new dependency — reuse
   `langchain-openai`. This adds a DB table (with vectors), a `Provenance` value, an
   embedding config, and a network call during answering, so it is **ask-first**
   (SPEC.md §8) and requires a SPEC update before implementation. Tasks T17–T19.

## Task List

**Status lives in `tasks/board.md` — the single source of truth.** This section is an
ordered index only; task definitions are in `tasks/todo.md`. Do not add status
checkboxes here.

| Task | Title | Phase |
|---|---|---|
| T1 | Project scaffold, tooling, config templates, placeholder stubs | 0 |
| T2 | `state` — SQLite schema + repository | 0 |
| T3 | `session` — browser, profile, `login` | 0 |
| T4 | `guard` — pacing, cap, hours, STOP | 0 |
| T5 | `discovery` (partial) — read job, detect Easy Apply | 1 |
| T6 | `answering` — facts rules + provenance | 1 |
| T7 | `filling` — single-step fields, resume upload, screenshots | 1 |
| T8 | `review-gate` + minimal graph + `run --url --dry-run` | 1 |
| T9 | LLM client (OpenRouter) + structured output | 2 |
| T10 | `answering` — LLM integration + `NEEDS_REVIEW` | 2 |
| T11 | `routing` — resume auto-index + selection | 2 |
| T12 | `discovery` — search, filters, dedupe | 2 |
| T13 | `filling` — multi-step navigation | 3 |
| T14 | `filling` — form fields + unknown handling | 3 |
| T15 | `orchestration` — run loop, checkpointing, crash resume, `status` | 3 |
| T16 | Guarded live validation (operational, 5–10/day) | 4 |
| T17 | `state` — learned-answer store (`learned_answers`) + `LEARNED` provenance | 2 |
| T18 | `answering` — learned-memory lookup (OpenRouter embeddings) before asking | 2 |
| T19 | `review-gate` — capture + remember human answers | 3 |

Task numbering is a stable identifier, not file order: T17–T19 are appended but
execute in Phase 2/3 by dependency (they follow T10/T8). T17–T19 are the
learned-answers feature (Architecture Decision 9); T17 is the ask-first schema slice.

**Checkpoints** (criteria in `tasks/board.md`):

- **CP-A Foundation** — after T4
- **CP-B Riskiest assumption proven** — after T8; the go/no-go gate
- **CP-C Discovery + intelligence** — after T12
- **CP-D Complete** — after T15

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| LinkedIn account restriction from automation | High | Guard caps/pacing/hours, `--dry-run` default early, start at 5–10/day (Task 16), stop-on-signal |
| Easy Apply DOM changes break the automation | High | browser-use agent reads the page semantically (no hand-maintained DOM selectors); integration smoke before each scaling step |
| LLM produces a plausible wrong answer | High | Facts rules take precedence; confidence threshold → `NEEDS_REVIEW`; human gate on every submit; criterion 11 is the acceptance test |
| Resume auto-index mis-maps a resume | Medium | Overrides in `resumes.yaml`; low confidence falls back to `default_variant` **and is flagged at review** |
| Review latency makes the tool abandoned | Medium | One-at-a-time review was chosen deliberately; measure take-over rate during Task 16 |
| LangGraph state/dependency complexity | Low | Thin nodes, I/O in tools, graph wired last (Task 15) |
| Placeholder stubs drift into invented behavior | Low | Explicit SPEC §4 note; scaffold task creates them docstring-only |
| Learned-answer embeddings unavailable/misbehaving on OpenRouter | Medium | Verify the embeddings endpoint + a model id before T18; if unsupported, fall back to the deterministic matcher or a different provider — ask first, do not silently degrade |

## Open Questions

None blocking. Non-blocking items are tracked in SPEC §11 "Still open":
default OpenRouter model id, real `facts.yaml` contents, and the proposed Ctrl-C
default (leave application `filled`, re-offered at the gate).

## Parallelization Notes

Single agent, so this is sequential. If a second session is ever available, these are
safely independent: Task 6 ∥ Task 9, and Task 11 ∥ Task 12 (different node files, no
shared contract beyond `JobState`/`Answer` types, which Task 2 freezes).
