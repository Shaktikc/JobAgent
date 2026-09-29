# Spec: AutoJobApply (MVP)

Status: draft — awaiting human approval. Date: 2026-09-29.
Source of truth for what we're building, why, and how we'll know it's done.
Idea one-pager: `docs/ideas/auto-job-apply.md`

---

## 1. Objective

Build a single-user, local automation agent that turns LinkedIn Easy Apply into a
**review-and-approve** workflow: search jobs from your criteria, read the job,
route the right resume variant, fill every Easy Apply form question, and **pause
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
| `routing` | Select resume variant for a job from mapping config | discovery, state |
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
| LLM | One provider, configured via env var (`AUTOJOB_LLM_PROVIDER`); `langchain-anthropic` or `langchain-openai`. Structured output for answers. |
| Config validation | Pydantic v2 + PyYAML |
| Persistence | SQLite via stdlib `sqlite3` (no ORM for MVP) |
| Resume text | `pypdf` |
| Terminal UI | `rich` |
| Tests | `pytest` (+ `pytest` unit fixtures; browser e2e marked and run manually) |
| Lint / format / types | `ruff`, `mypy` |

Dependencies live in `requirements.txt` (pinned). No dependency is added without
asking first (see Boundaries).

---

## 3. Commands

All run from the repo root. On Windows, activate the venv first.

```
# Setup
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# First-time auth: opens browser, you log in to LinkedIn manually, session persists
python -m autojobapply login

# Main run: search -> route -> fill -> terminal review -> (approve) submit
python -m autojobapply run

# Fill and review but NEVER submit (also the default during early validation)
python -m autojobapply run --dry-run

# Discovery only: populate the DB with matching jobs, fill nothing
python -m autojobapply search

# Inspect recorded state
python -m autojobapply status

# Quality gates
pytest -m "not e2e"        # unit/integration, no browser required — run before commit
pytest -m e2e              # manual smoke against a logged-in profile, never in CI
ruff check . --fix
ruff format .
mypy src
```

---

## 4. Project Structure

```
SPEC.md                     → this document
requirements.txt
config/                     → user-editable YAML (see §7)
  search.yaml               → titles, locations, filters, exclusions
  resumes.yaml              → resume filename -> role keywords mapping
  facts.yaml                → facts + hard rules for sensitive questions
resumes/                    → your resume variants (PDF), one per role type
src/autojobapply/
  __main__.py               → entry point
  cli.py                    → argument parsing, command dispatch
  config.py                 → Pydantic models + YAML loaders
  logging_setup.py          → structured logging config
  state/                    → SQLite schema, models, repository
  session/                  → browser launch, profile, LinkedIn page primitives
  guard/                    → pacing, daily cap, business hours, STOP sentinel
  discovery/                → search, job-card harvest, filters, job detail, classify
  routing/                  → resume variant selection
  answering/                → facts rule engine, LLM answer generation, provenance
  filling/                  → Easy Apply modal automation, selectors
  review/                   → terminal review UI
  graph/                    → LangGraph nodes + workflow, run-loop state
tests/
  unit/                     → pure-logic tests, no network/browser
  e2e/                      → marked browser smoke tests
  fixtures/                 → saved HTML samples for selector tests
data/                       → runtime, gitignored
  autojobapply.db           → SQLite
  profile/                  → dedicated Chromium profile (cookies)
  artifacts/                → per-job screenshots on failure
  STOP                      → sentinel file; if present, guard halts everything
docs/
  ideas/auto-job-apply.md
```

---

## 5. Code Style

Pure logic is separated from I/O so it can be tested without a browser. Modules
that touch the network or browser take their dependencies as explicit arguments.

```python
# src/autojobapply/routing/router.py
from __future__ import annotations

from dataclasses import dataclass

from autojobapply.config import ResumeVariant


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
  Pydantic models; module names singular (`routing/router.py`, not `routers.py`).
- Type hints on every function signature; `from __future__ import annotations`.
- Pydantic v2 models for all config and all LLM structured output; never parse
  LLM free text with regex.
- Every answer produced by `answering` carries a `Provenance` enum value
  (`RESUME`, `FACTS_RULE`, `LLM_GUESS`) plus a confidence — no exceptions.
- No bare `except:`; catch specific exceptions and log with context.
- Log via stdlib `logging` with structured extras (`job_id=`, `module=`,
  `answer_field=`); never log PII or full resume contents.
- Selectors are centralized in `filling/selectors.py` — never inline in logic.
- Secrets only from environment / `.env` (gitignored).

---

## 6. Testing Strategy

- **Unit (`pytest -m "not e2e"`, run before every commit):** config loading and
  validation; search filter + dedupe; role classification; `routing.route_resume`;
  facts rule engine; provenance assignment; `state` repository against an
  in-memory SQLite; guard cap/business-hours logic. No network, no browser.
- **Selector tests:** parse saved HTML fixtures in `tests/fixtures/` to assert
  `filling/selectors.py` still resolves the expected nodes.
- **E2E (`pytest -m e2e`, manual, never in CI):** launch the real browser against
  the logged-in profile, run one Easy Apply flow in `--dry-run`, assert it reaches
  the review gate without submitting. Requires a human-logged-in session.
- **Coverage expectation:** logic modules (`routing`, `answering/rules`,
  `guard`, `state`, `discovery` filters) should be well covered by unit tests.
  Browser-driving modules are covered by e2e smoke, not unit coverage — do not
  mock Playwright into unit tests.
- Tests must never perform a real submission. E2E always uses `--dry-run`.

---

## 7. Configuration Contracts

**`config/search.yaml`**
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

**`config/resumes.yaml`**
```yaml
variants:
  - file: resumes/data-analyst.pdf
    role_keywords: ["data analyst", "business analyst", "bi analyst"]
  - file: resumes/ml-engineer.pdf
    role_keywords: ["machine learning", "ml engineer", "data scientist"]
default_variant: resumes/data-analyst.pdf   # used when confidence is low; flagged in review
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

**Business hours / caps (env or `config/guard.yaml`):** default daily cap 30,
business hours 09:00–18:00 local, 20–90s randomized delay between actions.
Values are conservative by design; changing them requires asking first.

---

## 8. Boundaries

**Always**
- Run `ruff check .` and `pytest -m "not e2e"` before committing.
- Route every network/browser action through `guard`.
- Record every answer with provenance and confidence.
- Keep the dedicated `data/profile` separate from your everyday Chrome profile.
- Log every state transition with a timestamp.

**Ask first**
- Adding a dependency.
- Changing the database schema.
- Changing the daily cap, pacing delays, or business-hours window.
- Adding any code path that submits without the review gate.
- Switching LLM provider or model.
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
- **`routing`** — given a job title and configured variants, a variant is chosen;
  a low-confidence match falls back to `default_variant` **and is flagged in review**.
- **`answering`** — for every form field, exactly one answer is produced with a
  provenance value; fields outside the rule engine and below the LLM confidence
  threshold are marked `NEEDS_REVIEW` rather than silently guessed.
- **`filling`** — a real Easy Apply flow is completed up to the final Submit button
  without submitting; multi-step modals, required starred questions, and dropdowns
  are handled; a failure captures a screenshot to `data/artifacts/` and marks the
  job `failed`.
- **`review-gate`** — displays job title, company, URL, resume used, and every
  field/answer/provenance; accepts approve / reject / edit; reject performs no
  submission (`status=rejected`); approve performs exactly one submission and
  captures the confirmation (`status=applied`).
- **`orchestration`** — the LangGraph loop runs discovery → routing → answering →
  filling → review-gate per job until search results are exhausted or guard halts;
  state is checkpointed so a restart resumes mid-run.

---

## 10. Success Criteria (MVP done when)

1. `python -m autojobapply login` persists a LinkedIn session across restarts.
2. `python -m autojobapply search` populates SQLite with config-matching,
   Easy-Apply-only, deduped jobs.
3. Resume routing selects the expected variant on a fixture set of job titles.
4. For a fixture Easy Apply modal, every field receives an answer with provenance,
   and no field is left silently empty.
5. A real Easy Apply flow reaches the Submit button without submitting.
6. The terminal review shows job + every answer + provenance and accepts
   approve / reject / edit.
7. Reject ⇒ zero submissions. Approve ⇒ exactly one submission, captured.
8. `--dry-run` never submits, regardless of approval.
9. Guard refuses the 31st daily attempt and refuses out-of-hours runs.
10. A crash mid-run resumes without re-applying to already-applied jobs.
11. First 20 real applications produce **zero** wrong answers that you'd have
    caught by hand. (The trust criterion — if this fails, the checkpoint is theater.)

---

## 11. Open Questions

- **LLM provider/model** — default to whichever API key you already have. Which?
- **Role taxonomy** — how many resume variants, and their exact names/keywords?
- **Cap and hours** — accept 30/day, 09:00–18:00, 20–90s delays as the starting
  values? (Lower is safer during the first week.)
- **Screenshots** — capture a screenshot of every filled form for the record, or
  only on failure? (Costs disk, helps trust.)
- **Multi-step unknown widgets** — policy when a required question is an
  unrecognized custom widget: skip the job and mark `skipped`, or always surface
  it at review?
- **Promoted/scam filtering** — besides keyword exclusions, any rule for
  "Promoted" listings or thin/low-quality postings?
