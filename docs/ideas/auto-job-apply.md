# AutoJobApply — LangGraph LinkedIn Easy Apply Agent

Status: idea refined, awaiting spec. Date: 2026-09-29.

## Problem Statement

How might we turn LinkedIn Easy Apply into a review-and-approve workflow — an agent that searches jobs, routes the right resume, and fills every form — while a human approves each application before it is submitted?

## Recommended Direction

A LangGraph-driven browser agent operating your existing logged-in LinkedIn session. The pipeline: run a LinkedIn search from your criteria → read the job details → classify the role → pick the matching resume variant → fill the multi-step Easy Apply form → **pause in the terminal** showing the job summary and every answer with provenance ("from resume p.2" vs. "guessed — flagged") → you approve, reject, or edit → submit.

One application is reviewed at a time, interleaved with the agent's work — chosen over a batch queue, so throughput is capped by human attention (~30+/day). Search automation ships in the MVP per explicit decision, which makes anti-ban behavior (human-like pacing, daily caps, business-hours runs, hard stop switch) core MVP functionality, not a later hardening pass. Build order inside the MVP still starts with a single-job fill-and-review test, then layers search on top — same destination, risk-first sequencing.

## Key Assumptions to Validate

- [ ] **The account survives automation** (dealbreaker — includes both form-filling and search-scraping risk). Mitigate: human pacing, 30/day cap, business hours, stop-on-signal. Validate: 5–10/day for a week before scaling. One restriction and this idea dies.
- [ ] **Easy Apply forms fill reliably** across multi-step modals, required starred questions, custom dropdowns. Validate: correct-fill rate on the first 20 real jobs.
- [ ] **The review screen earns trust** — if the user re-checks everything in the browser anyway, the checkpoint is theater. Validate: track how often the user takes over.
- [ ] **Interleaved review at 30/day is sustainable** (~1–2 hrs/day of user attention).
- [ ] **Resume routing beats one master resume** — validate after the filling loop is stable.

## MVP Scope

**In:**

- The full loop: search → read → route → fill → review → submit
- Auth via existing logged-in browser session (no login automation)
- Multiple resume variants (one per role type) with agent-selected routing
- Terminal review with per-answer provenance, approve / reject / edit per application
- Anti-ban behavior: human-like pacing, daily cap (~30), business-hours runs, hard stop switch

**Out:** see below.

## Not Doing (and Why)

- **External ATS applies (Workday, Greenhouse, etc.)** — Easy Apply only; entirely different automation problem
- **Batch review queue** — interleaved one-at-a-time review chosen instead
- **Application tracking / outcomes dashboard** — Phase 2; needs data from real runs first
- **Answer-learning feedback loop** — needs outcome data to learn from
- **Multi-candidate / coach mode** — single user; adds auth and privacy liability for zero value
- **Login/credential automation** — existing session only; credential handling is security risk for no gain
- **Submit without review, ever** — the human checkpoint is the product

## Open Questions

- What defines a "good job" in search — titles, locations, seniority, Easy Apply + date-posted filters? Any scam/"Promoted" exclusion rules?
- How many resume variants, and how is each named/mapped to role types?
- Policy for sensitive questions (salary expectation, sponsorship, notice period, work auth) — facts file, per-question rules, or always ask at review?
- Where does run state live — applied log, pending, skipped, per-run session resume?

## Decisions Made During Refinement

- Personal tool, target 30+ applications/day
- Agent runs the LinkedIn search (explicitly required in MVP, despite ban/fragility risk)
- Review checkpoint: pause in terminal, one application at a time (not batch)
- Resume input: multiple variants, one per role type; agent routes per job
- Stack constraint: LangGraph + existing LinkedIn session
