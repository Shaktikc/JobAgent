# Task 30 — Show total AI token usage and cost in the browser up to Easy Apply submission

**Status:** ⬜ Not started

**Goal:** Track every LLM call the agent makes while working on an Easy Apply
application and show the running total token count and monetary cost in the
browser. The totals must be visible while the application is being filled and
must be frozen and clearly displayed at the moment the application is submitted.
This gives the human visibility into AI usage and spend up to submission.

**Scope:** Task creation only is authorized now. Implementation and runtime
verification are pending. The user asked only for the task to be created.

## Dependencies

- Task 9's on-page status overlay
  (`src/tools/linkedin_status_overlay/`).
- Task 14/23's model routing (`Settings.llm`, `Settings.self_healing`).
- Task 22's automatic submission (`src/tools/linkedin_auto_submit.py`).
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
  `prompt_tokens`, `completion_tokens`, and `total_tokens`.
- The model id used for each call.
- A pricing table for the configured models. Add
  `data/model_pricing.json` with input/output USD per 1M tokens, for example:

  ```json
  {
    "xiaomi/mimo-v2.6-pro": {
      "input_per_million": null,
      "output_per_million": null
    },
    "deepseek/deepseek-v4.1-flash-1017": {
      "input_per_million": null,
      "output_per_million": null
    }
  }
  ```

  Fill in the real prices from the provider's current pricing. A `null` price
  means "unknown": show the tokens and mark the cost as unknown rather than
  guessing.
- `StatusReporter` / `emit_step` / `emit_llm` for browser updates.
- `AutoSubmitResult` for the submission snapshot.

## Steps

1. **Create a token usage accounting module** (new file, for example
   `src/tools/token_usage/` or `src/tools/token_usage.py`):
   - Define `TokenUsage` (input, output, total tokens) and per-model usage.
   - Define a `TokenUsageTracker` with:
     - `record(model, usage)` — add one call's usage;
     - `start_application(job_id)` — reset the per-application totals;
     - `finish_application()` — freeze the per-application totals;
     - `snapshot()` — return a copy of the current totals;
     - `application_totals` and `session_totals`.
   - Compute cost from the pricing table. Use clear rounding and keep costs per
     model and in total. The session totals never reset during a run; the
     application totals reset when a new Easy Apply application starts.
   - Make the tracker safe for concurrent async calls (for example an
     `asyncio.Lock` or atomic updates).
   - Prefer an explicit tracker passed to LLM call sites so tests can inject a
     fake. If a module-level singleton is used, expose a reset for tests.
   - Include a pure `format_metrics()` helper that renders a compact line such
     as `Tokens: 1,234 in / 567 out (1,801 total) · Cost: $0.0012`.
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
   - Show:
     - `Application: <tokens> tokens · <cost>` for the current Easy Apply
       application;
     - `Session: <tokens> tokens · <cost>` for the whole run.
   - Update the display after each LLM call. Keep it visible while the form is
     filled. It must not cover LinkedIn's buttons.
   - At submission, freeze the application totals and display a clear
     `Submitted: <tokens> tokens · <cost>` line. Keep the totals visible after
     submission until the next application starts or the run ends.
4. **Wire application boundaries**:
   - Reset the application totals when a new Easy Apply form is opened for a
     new job. Find the correct hook in the application loop
     (`src/tools/linkedin_apply_loop.py`,
     `src/tools/linkedin_easy_apply_open.py`, or the fill orchestration) and
     call `tracker.start_application(job_id)`.
   - On successful submission (`AutoSubmitResult("submitted")` in
     `src/tools/linkedin_auto_submit.py`), call
     `tracker.finish_application()` and display the frozen totals.
   - On skip/discard/failure, keep the spent tokens in the session total and
     reset the application total when the next job starts. Document this
     behavior.
5. **Configuration and docs**:
   - Add `data/model_pricing.json` with the known models and `null`/zero for
     unknown prices. Document how to update the prices.
   - Keep the currency USD for now. Add an optional env var only if needed.
   - Update `.env.example` and `README.md` with the new display and the pricing
     file.
   - The pricing file contains only public prices; never put credentials in it.
6. **Tests**:
   - Unit tests for `TokenUsageTracker`: accumulation, per-model cost, unknown
     price, reset, session vs application totals, and concurrent records.
   - Unit tests for `format_metrics`.
   - Tests for each LLM call site recording usage: a fake client returns a
     usage object; assert the tracker received the right model and tokens.
     Cover retries and failed calls.
   - Tests for the panel: assert the metrics row is created/updated and the
     activity line is preserved; assert the update does not throw when no page
     is bound.
   - Tests for the submission freeze: simulate `AutoSubmitResult("submitted")`
     and assert the application totals are frozen/displayed.
   - Update existing tests that fake LLM clients to include a `usage` attribute;
     make the tracker optional so existing tests do not break. If the tracker is
     required, update every fake.
   - Run the full unit suite and lint.
7. **Live verification**:
   - In a real LinkedIn session, start an Easy Apply application that triggers
     at least one LLM call (resume matching and/or a form answer).
   - Confirm the browser panel shows the token and cost totals, updates after
     each LLM call, and remains visible while the form is filled.
   - Submit the application (or use the configured auto-submit) and confirm the
     final totals are frozen/displayed at submission.
   - Compare the observed totals with the provider's usage report if available.
     If they differ, investigate and fix.
   - Confirm the panel does not intercept clicks and does not cover the form's
     buttons.
   - Do not declare done until the user explicitly confirms.

## Acceptance criteria

- The browser shows total input/output tokens and total cost for the AI agent's
  LLM calls.
- The totals update live during the Easy Apply application and are
  frozen/displayed at submission.
- The cost is computed from the configured pricing table; unknown prices are
  clearly marked, not guessed.
- The display does not break the existing status panel or intercept LinkedIn
  controls.
- Every LLM call site is instrumented; no call is silently omitted (except
  documented self-healing limitations).
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
  `src/tools/linkedin_easy_apply_open.py`, `data/model_pricing.json`,
  `.env.example`, `README.md`, and tests.
- Keep every file under the 415-line limit; split a module if it grows past it.
- The OpenAI response `usage` object may be `None` (some providers omit it).
  Handle it gracefully.
- The tracker must not make network calls per LLM call. Load pricing once at
  startup or lazily and cache it.
- Do not log API keys or full prompts. The metrics display must only show token
  counts and cost.
- If a bug is found and fixed during implementation, log it in
  `known Bugs/task_30_bugs.md` and update `known Bugs/bug_log.md` with symptom,
  root cause, fix, status, and evidence. Create the file without waiting for
  approval.
- Mark Task 30 ✅ **Done** in this file and `task/task.md` only after the
  implementation works, the live-browser check passes, and the user explicitly
  confirms.

## Open questions

- Should the totals be per application or cumulative for the whole run? This
  task assumes both are shown; the primary "up to submission" total is per
  application. If the user wants only the session total, the per-application
  display can be simplified.
- Should self-healing tokens be included? The repair runs in a subprocess; if
  its command does not expose usage, it will be excluded with a note. The user
  can decide whether to require it.
- Currency: USD only for now. The provider bills in USD.
