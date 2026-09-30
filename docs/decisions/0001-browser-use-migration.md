# ADR 0001 — Replace the Playwright browser layer with browser-use

- **Status:** Accepted
- **Date:** 2026-09-30
- **Deciders:** project owner, engineering agent
- **Supersedes:** the Playwright-based approach in `tools/browser.py`,
  `tools/linkedin.py` (browser half), `nodes/discover.py` (browser half) and
  `nodes/fill.py` (browser half).

## Context

The MVP drives LinkedIn with hand-written Playwright scripts: module-level CSS
selectors, deterministic clicks/typing, and a `guard` wrapper around every action.
That gives reproducibility, cheap operation, and selector-level unit tests.

The owner asked to replace Playwright with the **browser-use** AI agent and to
"rewrite the whole code". browser-use is an LLM-driven agent: you give it a goal
and a model, and it decides each action from the page's accessibility tree. It is
no longer literally Playwright (it speaks CDP directly), but it is still an LLM in
the loop on every step.

This is a different model of control, not a different driver, and it collides with
hard invariants the project is built on (`SPEC.md` §8):

| Invariant | Collision |
|---|---|
| No code path may submit without explicit human approval | An autonomous agent can click Submit itself. |
| Every browser/network action routes through `guard` (caps, hours, 20–90 s pacing, STOP) | The agent chooses its own actions; each one cannot be individually wrapped. |
| Selectors centralised; fixture-based selector tests; no mocked Playwright in unit tests | Selectors are replaced by an LLM; selector tests largely collapse. |
| Determinism and low cost | One paid LLM call per step, non-reproducible. |

## Decision

Adopt browser-use for the **browser-driving layer**, but **keep the safety
architecture unchanged** unless the owner explicitly amends `SPEC.md`:

- **The human submit gate stays.** The agent is only ever asked to *read* and
  *fill*, never to submit. `build_fill_task` embeds a hard no-submit instruction,
  and submission is a separate task introduced to the agent **only** by the review
  gate after explicit approval (outside `--dry-run`).
- **`guard` stays.** Each agent run is bracketed by `guard.check_stop()` and paced
  with `guard.pause_between_actions()`; the run is treated as one round-trip action.
- **The dedicated profile stays.** browser-use's `Browser` is launched with
  `user_data_dir = data/profile`. The everyday Chrome profile is never touched and
  login remains manual.
- **SQLite state, the facts rule engine, and `review-gate` are untouched** — they
  are browser-independent and already verified.

Scope is therefore "replace the browser layer", not "discard T1–T8". The migration
is carried out on `feature/browser-use-migration` and added as task **T17**; nothing
is deleted until the agent path is demonstrated end-to-end and CP-B is re-run.

### New shape

```
tools/browser_agent.py     # browser-use factory + agent runner (this file's subject)
tools/browser.py           # browser-use Browser launched on data/profile; login()
tools/linkedin.py          # reading via the agent's structured output
nodes/discover.py          # same JobState contract, agent-backed read
nodes/fill.py              # pure task builders + agent runner; submit is gate-only
graph.py / main.py         # async pipeline (browser-use is asyncio-native)
```

Pure, browser-free logic (task text, answer → `sensitive_data`, placeholders,
paths) lives in `tools/browser_agent.py` and is unit-tested with no browser and no
LLM. Only the live run requires the dependency and an OpenRouter key.

## Consequences

**Positive**
- One AI browser layer instead of fragile selector maintenance; fewer breakages when
  LinkedIn reshuffles its DOM.
- Structured output from the agent replaces hand-written parsing.

**Negative / accepted risks**
- Non-deterministic; needs an LLM key and costs money per step.
- The guard can no longer intercept every individual action — only gate whole runs.
  This is the most important trade-off and the reason the submit gate is preserved
  as a hard boundary.
- Live behaviour cannot be verified by unit tests; CP-B must be re-run by hand.

## Alternatives considered

1. **Keep Playwright.** Rejected by the owner's request; also brittle against DOM churn.
2. **Hybrid behind a flag.** Lower risk, but the owner asked for replacement, not an
   alternate path.
3. **Full ground-up rewrite discarding T1–T8.** Rejected: loses verified, browser-
   independent logic (guard, store, facts rules, review gate) for no safety benefit.

## Decision resolved by the owner

The owner confirmed the migration on 2026-09-30 and **did not** grant the agent
permission to submit. This ADR therefore stands as written: submission is a
human-gated, separate action.
