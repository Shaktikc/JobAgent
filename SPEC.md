# Spec: AutoJobApply (MVP)

Status: **APPROVED** 2026-09-29. Supersedes the draft of the same date.
Source of truth for what we're building, why, and how we'll know it's done.
Idea one-pager: `docs/ideas/auto-job-apply.md`

---

## 1. Objective

Build a single-user, local automation agent that turns LinkedIn Easy Apply into a
**review-and-approve** workflow: search jobs from your criteria, read the job,
route the right resume, fill every Easy Apply form question, and **pause
for your explicit terminal approval before submitting**. No application is ever
submitted without human approval.

**User:** one person (the repository owner) running this on their own Windows
machine, targeting 30+ Easy Apply submissions per day.

**Success looks like:** instead of filling forms by hand, you spend ~1–2 hours a
day reviewing pre-filled applications and pressing approve/reject, and at least
the first 20 real submissions go through with no wrong answers and no LinkedIn
account restriction.

### Capability Map (approved 2026-09-29)

| Module id | Responsibility | Depends on |
|---|---|---|
| `state` | SQLite persistence: jobs seen, status, answers given, dedupe, crash-resume | — |
| `session` | Browser lifecycle, existing LinkedIn session (persistent profile), page primitives, hard-stop switch | state |
| `guard` | Pacing/delays, daily cap (~30), business hours, stop-on-signal | state |
| `discovery` | Run search from config, harvest job cards, apply filters, extract job details, detect Easy Apply, classify role | session, guard, state |
| `routing` | Auto-index every resume in `resumes/`; select the best-matching resume for a job | discovery, state |
| `answering` | Map resume + facts file onto form questions via LLM; facts rules; per-answer provenance + confidence | routing, state |
| `filling` | Playwright automation of the multi-step Easy Apply modal | session, answering, guard |
| `review-gate` | Terminal review: show job + every answer with provenance; approve / reject / edit; sole authority to submit | filling, state |
| `orchestration` | LangGraph graph wiring modules into the run loop | all |

Dependency direction is one-way (no cycles). Build order (also risk-first):
`state` → `session` + `guard` → `discovery` → `routing` → `answering` →
`filling` → `review-gate` → `orchestration`.

**Risk note (explicit):** automated use of LinkedIn violates its User Agreement
and can result in account restriction. Pacing, caps, and business-hours limits
reduce probability but do not eliminate it. This risk is accepted knowingly by
the project owner and is not mitigable by engineering.

---

## 2. Tech Stack

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| Orchestration | LangGraph |
| Browser automation | Playwright (sync API, dedicated persistent Chromium profile) |
| LLM | **OpenRouter** (OpenAI-compatible) via `langchain-openai` with `base_url=https://openrouter.ai/api/v1`. Model chosen by env var (`AUTOJOB_LLM_MODEL`) so it can be switched freely between runs. Structured output is required — answers must come back as validated Pydantic objects, never prose. |
| Config validation | Pydantic v2 + PyYAML |
| Persistence | SQLite via stdlib `sqlite3` (no ORM for MVP) |
| Resume text | `pypdf` |
| Terminal UI | `rich` |
| Tests | `pytest`; unit + integration (browser smoke, marked, run manually) |
| Lint / format / types | `ruff`, `mypy` |

Dependencies are managed in `pyproject.toml` (Poetry; `ruff` for lint/format).
`langgraph.json` holds the compilation blueprint. No dependency is added without
asking first (see Boundaries).

---

## 3. Commands

All run from the repo root.

```
# Setup (Poetry)
poetry install
poetry run playwright install chromium

# First-time auth: opens the browser, you log in to LinkedIn manually, session persists
poetry run python -m src.main login

# Main run: search -> route -> answer -> fill -> terminal review -> (approve) submit
poetry run python -m src.main run

# Fill and review but NEVER submit (the default during early validation)
poetry run python -m src.main run --dry-run

# Discovery only: populate the DB with matching jobs, fill nothing
poetry run python -m src.main search

# Inspect recorded state
poetry run python -m src.main status

# Quality gates
poetry run pytest -m "not integration"   # unit + selector tests, no browser — before commit
poetry run pytest -m integration         # manual browser smoke against a logged-in profile
poetry run ruff check . --fix
poetry run ruff format .
poetry run mypy src
```

**One-time setup download.** `poetry run playwright install chromium` fetches a
dedicated Chromium build (~196 MB) plus a headless shell (~115 MB, ~310 MB total) into
the local Playwright cache. It is pulled during the Task 1 scaffold — not deferred —
so the scaffold's acceptance criteria can actually be verified. This is the only large
download in setup; `poetry install` itself is a few tens of MB of Python wheels.

---

## 4. Project Structure

```
AutoJobApply/
├── .opencode/                  # OpenCode project configuration & definitions
│   ├── agents.md               # Tech stack definitions, global rules, & setup configs
│   └── agents/                 # Custom specialized OpenCode agents
│       ├── plan.md             # Planning-mode agent
│       └── review.md           # Custom review subagent (permissions, model, system prompt)
│                               # NOTE: skills stay at .agents/skills/ (owner decision);
│                               #       .opencode/skills/ is intentionally NOT created
├── src/                        # Core application code (LangGraph orchestration)
│   ├── __init__.py
│   ├── main.py                 # Graph execution entry point & compilation
│   ├── configuration.py        # Configuration schemas (LLM variants, guard limits, retry flags)
│   ├── state.py                # LangGraph state definitions (shared memory, graph channels)
│   ├── graph.py                # The StateGraph builder and compiler
│   ├── nodes/                  # Pure functional graph nodes (state transition computations)
│   │   ├── __init__.py
│   │   ├── ingest.py           # [placeholder] retained verbatim — no MVP responsibility
│   │   ├── plan.py             # [placeholder] retained verbatim — no MVP responsibility
│   │   ├── execute.py          # [placeholder] retained verbatim — no MVP responsibility
│   │   ├── verify.py           # [placeholder] retained verbatim — no MVP responsibility
│   │   ├── discover.py         # ACTIVE: search → harvest → filter → Easy Apply detect
│   │   ├── route.py            # ACTIVE: resume selection (auto-indexed from resumes/)
│   │   ├── answer.py           # ACTIVE: facts rules + LLM answers + provenance
│   │   ├── fill.py             # ACTIVE: Playwright Easy Apply modal automation + selectors
│   │   └── review.py           # ACTIVE: terminal review gate (approve/reject/edit)
│   └── tools/                  # Tools exposed directly to the LangGraph state
│       ├── __init__.py
│       ├── opencode_client.py  # [placeholder] retained verbatim — no target codebase here
│       ├── git_snapshot.py     # [placeholder] retained verbatim — no code rollback here
│       ├── browser.py          # ACTIVE: Playwright session/profile/page primitives
│       ├── linkedin.py         # ACTIVE: LinkedIn search + modal operations
│       ├── guard.py            # ACTIVE: pacing, daily cap, business hours, STOP sentinel
│       ├── store.py            # ACTIVE: SQLite persistence & dedupe
│       └── resume_parser.py    # ACTIVE: PDF → text
├── workspace/                  # [placeholder] isolates a target codebase — unused here
│   └── [target_codebase]/
├── config/                     # User-editable YAML (see §7)
│   ├── search.yaml             # titles, locations, filters, exclusions
│   ├── resumes.yaml            # resume filename -> role keywords mapping
│   └── facts.yaml              # facts + hard rules for sensitive questions
├── resumes/                    # Resumes (PDF) — any number, one per role you target
├── data/                       # Runtime, gitignored
│   ├── autojobapply.db         # SQLite
│   ├── profile/                # Dedicated Chromium profile (cookies)
│   ├── artifacts/              # Per-job screenshots on failure
│   └── STOP                    # Sentinel file; if present, guard halts everything
├── tests/                      # Testing infrastructure
│   ├── unit/                   # Independent node and tool logic
│   ├── integration/            # End-to-end graph runs (browser smoke, marked, manual)
│   └── fixtures/               # Saved HTML samples for selector tests
├── docs/ideas/auto-job-apply.md
├── .env.example                # Managed API keys, LLM/Ollama config, or proxy setups
├── langgraph.json              # Compilation blueprint for LangGraph cloud/managed infra
├── pyproject.toml              # Unified package & dependency management (Poetry / Ruff)
└── SPEC.md                     # This document
```

**Placeholder note.** `nodes/ingest.py`, `nodes/plan.py`, `nodes/execute.py`,
`nodes/verify.py`, `tools/opencode_client.py`, `tools/git_snapshot.py`, and
`workspace/` are retained verbatim from the owner's template by explicit decision.
They carry **no MVP responsibility** — this project modifies no target codebase and
has nothing to roll back. They are created as docstring-only stubs so the skeleton
matches the template; they must not be filled with invented behavior.

**Module-id → file mapping** (keeps §9 traceable to the approved capability map):

| Module id | Lives in |
|---|---|
| `state` | `src/tools/store.py` — persistence. Distinct from `src/state.py`, which is LangGraph channels. |
| `session` | `src/tools/browser.py`, `src/tools/linkedin.py` |
| `guard` | `src/tools/guard.py` |
| `discovery` | `src/nodes/discover.py` |
| `routing` | `src/nodes/route.py` |
| `answering` | `src/nodes/answer.py` |
| `filling` | `src/nodes/fill.py` |
| `review-gate` | `src/nodes/review.py` |
| `orchestration` | `src/graph.py`, `src/state.py`, `src/main.py`, `src/configuration.py` |

---

## 5. Code Style

Pure logic is separated from I/O so it can be tested without a browser. Modules
that touch the network or browser take their dependencies as explicit arguments.

```python
# src/nodes/route.py
from __future__ import annotations

from dataclasses import dataclass

from src.configuration import ResumeVariant


@dataclass(frozen=True)
class RouteResult:
    variant: ResumeVariant
    matched_keywords: tuple[str, ...]
    confidence: float


def route_resume(job_title: str, variants: list[ResumeVariant]) -> RouteResult:
    """Pick the best-matching resume variant. Pure function: no I/O, no LLM."""
    if not variants:
        raise ValueError("no resume variants configured")
    ...
```

Conventions:
- `snake_case` for functions/modules/variables; `PascalCase` for classes and
  Pydantic models; node modules are singular (`nodes/route.py`, not `nodes/routes.py`).
- Type hints on every function signature; `from __future__ import annotations`.
- Pydantic v2 models for all config and all LLM structured output; never parse
  LLM free text with regex.
- Every answer produced by `nodes/answer.py` carries a `Provenance` enum value
  (`RESUME`, `FACTS_RULE`, `LLM_GUESS`, `NEEDS_REVIEW`) plus a confidence — no exceptions.
- No bare `except:`; catch specific exceptions and log with context.
- Log via stdlib `logging` with structured extras (`job_id=`, `module=`,
  `answer_field=`); never log PII or full resume contents.
- Selectors are centralized as module-level constants in `nodes/fill.py` — never inline in logic.
- `configuration.py` is the single source of settings; nodes receive config explicitly,
  never read env vars directly.
- Secrets only from environment / `.env` (gitignored).

---

## 6. Testing Strategy

- **Unit (`poetry run pytest -m "not integration"`, run before every commit):** lives
  in `tests/unit/`. Config loading and validation (`configuration.py`); search filter
  and dedupe; role classification; `nodes/route.py`; facts rule engine; provenance
  assignment; `tools/store.py` against an in-memory SQLite; `tools/guard.py` cap and
  business-hours logic. No network, no browser.
- **Selector tests:** parse saved HTML fixtures in `tests/fixtures/` to assert the
  selector constants in `nodes/fill.py` still resolve the expected nodes.
- **Integration (`poetry run pytest -m integration`, manual, never in CI):** lives in
  `tests/integration/`. Launches the real browser against the logged-in profile, runs
  one Easy Apply flow in `--dry-run`, and asserts it reaches the review gate without
  submitting. Requires a human-logged-in session.
- **Coverage expectation:** logic-bearing files (`nodes/route.py`, the rules in
  `nodes/answer.py`, `tools/guard.py`, `tools/store.py`, the filters in
  `nodes/discover.py`) should be well covered by unit tests. Browser-driving code is
  covered by integration smoke, not unit coverage — do not mock Playwright into unit
  tests.
- Tests must never perform a real submission. Integration always uses `--dry-run`.

---

## 7. Configuration Contracts

**`config/search.yaml`** — filtering is **keyword-based only**, per decision. There are
no built-in heuristics: "Promoted" listings are *not* excluded, and there is no
company-logo/age/agency pattern matching. Only `exclude_keywords` and
`exclude_companies` drop postings.
```yaml
keywords: ["data analyst", "business analyst"]
location: "United States"
remote: true
easy_apply_only: true
posted_within_days: 3
experience_levels: ["mid_senior", "associate"]
exclude_keywords: ["unpaid", "commission only", "staffing agency"]
exclude_companies: []
max_results_per_run: 40
```

**Resume routing (auto-indexed, per decision).** You may drop **any number** of PDFs
into `resumes/`; each is auto-mapped to the jobs it fits. There is no fixed taxonomy
and no required naming convention. On first run (and whenever a file's hash changes),
the agent indexes every resume: parse the PDF text, then ask the LLM to extract the
role titles and keywords that resume targets, caching the result in SQLite. Job titles
and descriptions are then matched against the index, and the best-scoring resume is
used.

**`config/resumes.yaml`** — *optional* overrides only. Present for cases where you want
to correct the auto-index or pin a forced mapping.
```yaml
overrides:
  - file: resumes/data-analyst.pdf
    role_keywords: ["data analyst", "business analyst", "bi analyst"]  # replaces auto-extracted
default_variant: resumes/data-analyst.pdf   # used when confidence is low; flagged in review
reindex: false                              # set true to force a full re-index on next run
```

**`config/facts.yaml`** — facts plus hard rules. The rule engine takes precedence
over the LLM; anything not covered is flagged for review.
```yaml
facts:
  work_authorization: "US citizen"
  requires_sponsorship: false
  notice_period: "2 weeks"
  desired_salary: "110000"
  years_experience: 4
  willing_to_relocate: false
rules:
  - match: "sponsor"
    answer: "No"
    provenance: FACTS_RULE
  - match: "salary|compensation|expected pay"
    answer_from: facts.desired_salary
    provenance: FACTS_RULE
```

**Business hours / caps (env or `config/guard.yaml`):** **confirmed** daily cap 30,
business hours 09:00–18:00 local, 20–90s randomized delay between actions. Changing
any of these values requires asking first.

---

## 8. Boundaries

**Always**
- Run `ruff check .` and `pytest -m "not integration"` before committing.
- Route every network/browser action through `guard`.
- Record every answer with provenance and confidence.
- Keep the dedicated `data/profile` separate from your everyday Chrome profile.
- Log every state transition with a timestamp.

**Ask first**
- Adding a dependency.
- Changing the database schema.
- Changing the daily cap, pacing delays, or business-hours window.
- Adding any code path that submits without the review gate.
- Switching the LLM provider (model switching *within* OpenRouter is expected and free).
- Changing `config/*.yaml` structural shape (not just values).

**Never**
- Commit `.env`, cookies, the Chromium profile, or resumes containing PII.
- Submit an application without explicit human approval at `review-gate`.
- Bypass, disable, or "temporarily" skip `guard`.
- Remove a failing test to get to green.
- Automate LinkedIn login with stored credentials (manual login only).
- Use the everyday Chrome profile.

---

## 9. Per-Module Acceptance Criteria

- **`state`** — SQLite schema creates on first run; jobs are deduped by LinkedIn job
  id; a killed process resumes without re-processing `applied` jobs; statuses are
  `seen | skipped | filled | rejected | applied | failed`.
- **`session`** — `login` persists a session that survives a full process restart;
  the browser is only launched via this module; the `data/STOP` sentinel halts
  actions within one step.
- **`guard`** — the 31st application attempt in a calendar day is refused with a
  clear message; runs outside business hours refuse to start; randomized delay is
  applied between actions; a rate-limit/checkpoint signal stops the run immediately.
- **`discovery`** — a run populates the DB with jobs matching `search.yaml`,
  Easy-Apply-only, within the date window, deduped, with excluded keywords/companies
  filtered out; Easy Apply availability is detected before the job is queued.
- **`routing`** — every PDF in `resumes/` is indexed (LLM-extracted role keywords,
  cached by file hash) with no naming convention required and no fixed taxonomy; a
  resume is chosen per job by keyword match; `resumes.yaml` overrides win when present;
  a low-confidence match falls back to `default_variant` **and is flagged in review**.
- **`answering`** — for every form field, exactly one answer is produced with a
  provenance value; fields outside the rule engine and below the LLM confidence
  threshold are marked `NEEDS_REVIEW` rather than silently guessed.
- **`filling`** — a real Easy Apply flow is completed up to the final Submit button
  without submitting; multi-step modals, required starred questions, and dropdowns
  are handled; a screenshot of the filled form is saved to `data/artifacts/` for
  **every** application; an unrecognized required widget is left blank and surfaced at
  review as `NEEDS_REVIEW` (never silently guessed, never a silent job skip); a hard
  failure captures a screenshot and marks the job `failed`.
- **`review-gate`** — displays job title, company, URL, resume used, and every
  field/answer/provenance; accepts approve / reject / edit; reject performs no
  submission (`status=rejected`); approve performs exactly one submission and
  captures the confirmation (`status=applied`).
- **`orchestration`** — the LangGraph loop runs discovery → routing → answering →
  filling → review-gate per job until search results are exhausted or guard halts;
  state is checkpointed so a restart resumes mid-run.

---

## 10. Success Criteria (MVP done when)

1. `poetry run python -m src.main login` persists a LinkedIn session across restarts.
2. `poetry run python -m src.main search` populates SQLite with config-matching,
   Easy-Apply-only, deduped jobs.
3. Resumes dropped into `resumes/` are auto-indexed with no naming convention, and
   routing selects the expected resume on a fixture set of job titles.
4. For a fixture Easy Apply modal, every recognized field receives an answer with
   provenance; unrecognized required widgets appear at review as `NEEDS_REVIEW`.
5. A real Easy Apply flow reaches the Submit button without submitting.
6. The terminal review shows job + every answer + provenance and accepts
   approve / reject / edit.
7. Reject ⇒ zero submissions. Approve ⇒ exactly one submission, captured.
8. `--dry-run` never submits, regardless of approval.
9. Guard refuses the 31st daily attempt and refuses out-of-hours runs.
10. A crash mid-run resumes without re-applying to already-applied jobs.
11. First 20 real applications produce **zero** wrong answers that you'd have
    caught by hand. (The trust criterion — if this fails, the checkpoint is theater.)
12. A screenshot of the filled form exists in `data/artifacts/` for every application
    that reached review.
13. Swapping `AUTOJOB_LLM_MODEL` changes the model with **no code change**; two
    different OpenRouter models both complete a fixture answering task.

---

## 11. Decisions Log

All open questions were resolved on 2026-09-29.

| Question | Decision |
|---|---|
| LLM provider/model | **OpenRouter**, model set by `AUTOJOB_LLM_MODEL`. Models are swapped freely between runs; no code change. |
| Resume variants | **Any number.** Auto-indexed from `resumes/` (LLM-extracted role keywords, cached by file hash) and matched to jobs automatically. `resumes.yaml` holds optional overrides only. No fixed taxonomy, no naming convention. |
| Cap and hours | **Confirmed:** 30/day, 09:00–18:00 local, 20–90s randomized delays. |
| Screenshots | **Every application** — PNG of the filled form saved to `data/artifacts/` before review. |
| Unknown widgets | **Surface at review** as `NEEDS_REVIEW`, left blank. Never a silent guess, never a silent skip. |
| Spam filtering | **Keyword list only** — `exclude_keywords` / `exclude_companies`. No built-in heuristics; "Promoted" listings are not excluded. |

### Still open (non-blocking)

- **Default OpenRouter model id** — pick per run; the spec requires only that any
  chosen model works. Suggested starting point: a cheap, fast model for form answering.
- **`facts.yaml` contents** — your real work authorization, salary expectation, notice
  period, and any hard "never answer yes to X" rules. This is data you supply, not a
  spec decision; the MVP runs with the template values until you replace them.
- **Ctrl-C mid-review behavior** — should an interrupted review leave the application
  `filled` (resumable) or `rejected`? Proposed default: `filled`, so a re-run re-offers
  it at the gate rather than losing it.
