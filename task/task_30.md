# Task 30 — Show total AI token usage and cost in the browser up to Easy Apply submission

**Status:** 🟡 In progress

**Goal:** Track every LLM call the agent makes during the run and show the
cumulative **session** total token count and monetary cost in the browser. The
total must be visible while applications are being filled. At the moment an Easy
Apply application is submitted — manually or automatically — capture and display
the session total up to that point as a frozen "up to submission" figure. The
session total continues to accumulate across jobs; skipped, discarded, and failed
applications count toward it because those tokens were still spent.

**Scope:** Task creation only is authorized now. Implementation and runtime
verification are pending. The user asked only for the task to be created.

## Decisions (confirmed with the user)

- **Totals shown:** session total only (no separate per-application total in the
  browser).
- **Skipped/discarded/failed jobs:** their tokens count toward the session total.
- **Self-healing:** include its tokens when the repair command exposes usage;
  otherwise mark it as excluded.
- **Pricing:** fetch from the OpenRouter models API first and fall back to a local
  `data/model_pricing.json`.
- **Display:** extend the existing bottom-left status panel with a metrics row.
- **Submission trigger:** both manual submission (apply loop) and automatic
  submission (`AutoSubmitResult`).
- **Cached tokens:** handle them when the provider reports cached prompt tokens
  and a discounted cached price.

## Dependencies

- Task 9's on-page status overlay
  (`src/tools/linkedin_status_overlay/`).
- Task 14/23's model routing (`Settings.llm`, `Settings.self_healing`).
- Task 22's automatic submission (`src/tools/linkedin_auto_submit.py`).
- Task 8's manual submission detection
  (`src/tools/linkedin_apply_loop.py`).
- Task 3/10/12's LLM call sites:
  - `src/tools/resume_descriptions/client.py`
  - `src/tools/llm_answers.py`
  - `src/tools/llm_answer_reasoning.py`
  - `src/tools/job_context_answers/chooser.py`
- The self-healing repair command
  (`src/tools/self_healing/recovery/repair.py`); its usage is optional and may
  be unavailable because it runs in a subprocess.

## Inputs

- The OpenAI-compatible response `usage` object from each LLM call:
  `prompt_tokens`, `completion_tokens`, `total_tokens`, and, when present,
  `prompt_tokens_details.cached_tokens`.
- The model id used for each call.
- Pricing data:
  - Primary source: OpenRouter's models endpoint, fetched once and cached.
  - Fallback: `data/model_pricing.json` with input/output USD per 1M tokens, for
    example:

  ```json
  {
    "xiaomi/mimo-v2.6-pro": {
      "input_per_million": null,
      "output_per_million": null,
      "cached_input_per_million": null
    },
    "deepseek/deepseek-v4.1-flash-1017": {
      "input_per_million": null,
      "output_per_million": null,
      "cached_input_per_million": null
    }
  }
  ```

  A `null` price means "unknown": show the tokens and mark the cost as unknown
  rather than guessing.
- `StatusReporter` / `emit_step` / `emit_llm` for browser updates.
- Submission signals: `submission_detected()` in the apply loop and
  `AutoSubmitResult("submitted")` in the automatic submitter.

## Steps

1. **Create a token usage accounting module** (new file, for example
   `src/tools/token_usage/` or `src/tools/token_usage.py`):
   - Define `TokenUsage` (input, output, cached, total tokens) and per-model
     usage.
   - Define a `TokenUsageTracker` with:
     - `record(model, usage)` — add one call's usage;
     - `snapshot()` — return a copy of the current session totals;
     - `session_totals` — the cumulative totals for the whole run.
   - The session totals never reset during a run. Do not add a separate
     per-application total to the browser display.
   - Compute cost from the pricing provider. Keep costs per model and in total.
     Use clear rounding.
   - Handle cached prompt tokens: when the response reports cached tokens and the
     pricing data includes a cached input price, price those tokens at the
     discounted rate. If the cached price is unavailable, use the normal input
     rate or mark the cost as unknown.
   - Make the tracker safe for concurrent async calls (for example an
     `asyncio.Lock` or atomic updates).
   - Prefer an explicit tracker passed to LLM call sites so tests can inject a
     fake. If a module-level singleton is used, expose a reset for tests.
   - Include a pure `format_metrics()` helper that renders a compact line such
     as `Session: 1,234 in / 567 out (1,801 total) · Cost: $0.0012`.
   - Include a helper for the frozen submission snapshot, for example
     `Up to submission: 1,234 in / 567 out (1,801 total) · Cost: $0.0012`.
2. **Instrument every LLM call site** to record usage:
   - `resume_descriptions/client.py`: change `_chat_once` to return the reply
     text and the response usage (or the response object), and pass the usage to
     the tracker in `_chat`/`_ask_json`. Count every attempt, including the
     JSON-nudge retry and transient retries.
   - `llm_answers.py`: record usage after
     `client.chat.completions.create`.
   - `llm_answer_reasoning.py`: record usage after the client call.
   - `job_context_answers/chooser.py`: record usage after the client call.
   - Self-healing: if the repair command exposes usage (for example OpenCode
     JSON output), parse it and record it; otherwise document that self-healing
     usage is excluded and show a note. Do not block the feature on this.
   - Handle a missing `usage` object gracefully: count the call, record zero
     tokens, and mark the usage as unavailable. Do not crash.
3. **Add the browser display**:
   - Extend the on-page status panel
     (`src/tools/linkedin_status_overlay/panel_js.py`) with a metrics row below
     the latest activity line. Keep the existing single-line activity behavior
     and `pointer-events:none`.
   - Add a `StatusReporter.metrics(...)` method (or a new `emit_metrics`
     helper) that updates the metrics row without replacing the latest activity
     line. It must be best-effort and must not throw when no page is bound.
   - Show the live session total:
     `Session: <tokens> tokens · <cost>`.
   - Update the display after each LLM call. Keep it visible while the form is
     filled. It must not cover LinkedIn's buttons.
   - At submission, display a frozen snapshot in addition to the live session
     line:
     `Up to submission: <tokens> tokens · <cost>`.
     The frozen line remains visible until the run ends. The live session line
     keeps updating for later jobs.
4. **Wire submission boundaries**:
   - Manual submission: in `src/tools/linkedin_apply_loop.py`, when
     `submission_detected()` confirms the human's submission (the `"submitted"`
     path), call `tracker.snapshot()` and display the frozen "up to submission"
     total.
   - Automatic submission: in `src/tools/linkedin_auto_submit.py`, when
     `AutoSubmitResult("submitted")` is returned, do the same.
   - Do not reset the session total at submission or when a new job starts. The
     session total continues across jobs. Skipped, discarded, and failed
     applications are already included because their LLM calls were recorded.
   - Document this behavior.
5. **Pricing provider and docs**:
   - Add a pricing provider that fetches OpenRouter's models endpoint once and
     caches the result. Fall back to `data/model_pricing.json` when the API is
     unavailable or the model is not listed. Do not make a network call per LLM
     call.
   - Add `data/model_pricing.json` with the known models and `null`/zero for
     unknown prices. Document how to update the prices.
   - Keep the currency USD for now. Add an optional env var only if needed.
   - Update `.env.example` and `README.md` with the new display, the pricing
     source order, and the fallback file.
   - The pricing file contains only public prices; never put credentials in it.
6. **Tests**:
   - Unit tests for `TokenUsageTracker`: accumulation, per-model cost, cached
     tokens, unknown price, session total, snapshot, and concurrent records.
   - Unit tests for `format_metrics` and the submission-snapshot helper.
   - Tests for each LLM call site recording usage: a fake client returns a
     usage object; assert the tracker received the right model and tokens.
     Cover retries and failed calls. Cover cached token counts.
   - Tests for the pricing provider: API fetch, cache reuse, fallback to the
     local file, and unknown models.
   - Tests for the panel: assert the metrics row is created/updated and the
     activity line is preserved; assert the update does not throw when no page
     is bound.
   - Tests for the submission freeze: simulate both manual and automatic
     submission and assert the frozen "up to submission" total is displayed and
     the session total continues.
   - Update existing tests that fake LLM clients to include a `usage` attribute;
     make the tracker optional so existing tests do not break. If the tracker is
     required, update every fake.
   - Run the full unit suite and lint.
7. **Live verification**:
   - In a real LinkedIn session, start an Easy Apply application that triggers
     at least one LLM call (resume matching and/or a form answer).
   - Confirm the browser panel shows the session token and cost totals, updates
     after each LLM call, and remains visible while the form is filled.
   - Submit the application manually and, separately, with the configured
     auto-submit. Confirm the frozen "up to submission" total is displayed in
     both cases and the live session total continues afterward.
   - Confirm tokens spent on a skipped or discarded application are included in
     the session total.
   - Compare the observed totals with the provider's usage report if available.
     If they differ, investigate and fix.
   - Confirm the panel does not intercept clicks and does not cover the form's
     buttons.
   - Do not declare done until the user explicitly confirms.

## Acceptance criteria

- The browser shows the cumulative session total input/output tokens and total
  cost for the AI agent's LLM calls.
- The session total updates live during Easy Apply applications.
- At submission (manual or automatic), a frozen "up to submission" snapshot of
  the session total is displayed and remains visible.
- Tokens spent on skipped, discarded, and failed applications count toward the
  session total.
- The cost is computed from the pricing provider: OpenRouter API first, local
  `data/model_pricing.json` fallback. Cached tokens are handled when reported.
  Unknown prices are clearly marked, not guessed.
- The display does not break the existing status panel or intercept LinkedIn
  controls.
- Every LLM call site is instrumented; self-healing usage is included when
  available. No call is silently omitted except documented self-healing
  limitations.
- Unit tests and live-browser verification pass.
- The task remains 🟡 In progress until the user explicitly confirms.

## Implementation notes

- Primary files: new `src/tools/token_usage/` (or
  `src/tools/token_usage.py`), `src/tools/resume_descriptions/client.py`,
  `src/tools/llm_answers.py`, `src/tools/llm_answer_reasoning.py`,
  `src/tools/job_context_answers/chooser.py`,
  `src/tools/linkedin_status_overlay/panel_js.py`,
  `src/tools/linkedin_status_overlay/status_reporter.py`,
  `src/tools/linkedin_status_overlay/__init__.py`,
  `src/tools/linkedin_auto_submit.py`, `src/tools/linkedin_apply_loop.py`,
  `data/model_pricing.json`, `.env.example`, `README.md`, and tests.
- Keep every file under the 415-line limit; split a module if it grows past it.
- The OpenAI response `usage` object may be `None` (some providers omit it).
  Handle it gracefully.
- The tracker must not make network calls per LLM call. Fetch pricing once and
  cache it.
- Do not log API keys or full prompts. The metrics display must only show token
  counts and cost.
- If a bug is found and fixed during implementation, log it in
  `known Bugs/task_30_bugs.md` and update `known Bugs/bug_log.md` with symptom,
  root cause, fix, status, and evidence. Create the file without waiting for
  approval.
- Mark Task 30 ✅ **Done** in this file and `task/task.md` only after the
  implementation works, the live-browser check passes, and the user explicitly
  confirms.

## Additional requirement (user requested November 23, 2026)

- Show the number of applications scanned and submitted beside session token/cost
  totals and in the frozen submission snapshot.
- Scanned means distinct jobs opened for evaluation (including opening attempts
  that fail, later skips, and discards), excluding already-applied cards.
- Submitted means confirmed submissions, deduplicated per job.
- Reset these counts with the session; preserve counts across jobs.
