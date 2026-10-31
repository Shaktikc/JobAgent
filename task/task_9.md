# Task 9 — Show live progress in the browser UI (what the agent and the LLM are doing)

**Status:** ✅ Done

**Goal:** While a run is active, show an always-updating status panel **in the
browser, on the same LinkedIn page** the agent is automating, that tells the
human — in plain language — exactly what the code is doing at each moment. Every
major step is shown as the panel's single current line ("Please wait — searching
for '<chosen query>' jobs…"), replaced on each update, and whenever the
**LLM** is invoked the panel says **exactly what the
LLM is doing** (which resume it is summarizing, which job it is matching
against, which form question it is classifying) and then what the LLM decided.
The panel is read-only feedback: it never changes the page or blocks automation.

**Preconditions**
- Tasks 1-8 are complete: the agent has browser steps (login, search, select,
  read description, fill, skip/applied, pagination, submit-wait, next job) and
  LLM calls (Task 3.2 resume description/matching, Task 4.1 answer choosing).
- A live browser session exists for the run (`browser_run_id`), so a page is
  available to render the panel into.
- The existing CLI logging (`progress`/`notify` → `print`) keeps working; the
  panel is an additional, on-page view of the same events.

**Inputs**
- A short, human-readable status message for each step.
- An optional **actor** label (`agent` or `llm`) so LLM activity is clearly
  marked as the LLM, not the browser code.
- An optional detail string (the job title, the resume name, the question text,
  the chosen answer, the rationale, the model name).
- The live page/session for the run (resolved from `browser_run_id`).

**Steps**
1. Add one shared helper that injects a fixed status panel into the current
   page and updates it in place (never stacks a new panel per message).
2. Emit a status update at the start of every major agent step, phrased as
   "Please wait — …" (see the examples below).
3. Emit a status update **before** every LLM call saying exactly what the LLM is
   about to do and on which input, and **after** it returns saying what it
   decided (or that it could not decide).
4. Show only the latest step in the panel (each update replaces the previous
   line), so the human always sees what is happening now without a growing list.
5. Make the panel visually distinct from Task 5's "does not know this answer"
   banner and Task 3.1's "needs a resume" banner, so all three can coexist — and
   keep it **in front of LinkedIn's Easy Apply modal**.
6. Treat the panel as best-effort: a failed injection/update is logged and the
   run continues unchanged.
7. Remove/close the panel when the run finishes (cleanup), so no stale status is
   left on the page.

**Acceptance criteria**
- During a live run, the LinkedIn page shows a status panel that updates as the
  run progresses — one visible line per major step.
- Each major step is worded as a plain-language "Please wait — …" (or
  "Waiting for you — …" while the human owns the next action).
- Every LLM invocation is shown with an explicit `LLM:` label stating exactly
  what the LLM is doing (with its input) and, when it returns, what it decided.
- The panel updates in place (no duplicate/stacked panels) and shows only the
  latest step (each update replaces the previous line).
- The panel coexists with Task 5's answer banner and Task 3.1's resume banner.
- A panel failure never fails or blocks the run.
- The panel is removed/closed when the run ends.
- No secrets (API keys, tokens, credential text) ever appear in the panel.

**Notes**
- **Reuse the existing overlay pattern:** Task 5 (`linkedin_ask_human.py`) and
  Task 3.1 (`linkedin_best_matching_resume.py`) already render top-layer
  `popover` elements with `textContent` only and a `data-autojob-*` state
  attribute. The status panel should follow the same approach (own element id,
  own corner, no `<input>`, no markup injection).
- **Untrusted content:** page text (job titles, question labels, model replies)
  is untrusted data — set it with `textContent`, never `innerHTML`.
- **Same page, same session:** update through the run's live page
  (`get_run(run_id).page`) so the panel lives on the LinkedIn tab the agent is
  driving; do not open a new tab or window.
- **Do not block:** updates are fire-and-forget; a slow/failed evaluate must be
  swallowed (reuse `_safe` from `browser.py`) and never delay the step.
- **Never gate on the panel:** automation decisions must not depend on whether
  the panel rendered.
- **Stay in front of LinkedIn's modal:** the Easy Apply modal is itself a
  top-layer dialog whose backdrop is painted above any popover opened *before*
  it. The panel re-raises itself to the newest top-layer slot on every update
  (hide + re-show), so it stays visible in front of the modal — like Task 5's
  answer banner, which is shown later and is therefore already on top.
- Keep every file under the 415-line limit; split into a package if needed.

## Subtask 9.1 — Status overlay helper (inject, update, clear — best-effort)

**Status:** ✅ Done

**Goal:** Provide one small, testable module that renders and updates a status
panel on the current page, plus a reporter object the rest of the code calls to
push agent/LLM status. It must be safe when no page exists or the evaluate
fails.

**Preconditions**
- A live page object is available for at least some updates (the run may emit
  status before/after the page exists — those updates print to the CLI only).

**Inputs**
- The live `page` (or `None`).
- A message, an optional `actor` (`"agent"` / `"llm"`), and an optional detail.

**Steps**
1. Add the panel JS: create a fixed element (own id, e.g. `autojob-status`,
   bottom-left so it never overlaps Task 5's / Task 3.1's bottom-right banners)
   with a heading and a single current line; render in the browser's top layer
   (`popover="manual"`) and set text via `textContent`.
2. Add an update JS that finds-or-creates the panel, replaces the current line
   with the new message, and returns `true` (no history is kept).
3. Add a clear JS that removes the panel and resets its state.
4. Add a reporter that wraps the existing CLI `notify` callback (so it can be
   passed where `progress=print` is passed today) and exposes:
   - `step(message)` — an agent step ("Please wait — …").
   - `llm(action, detail="")` — an LLM action (rendered with an `LLM:` label).
   - `clear()` — remove the panel at the end of the run.
   Each method prints to the CLI as before and, when a page is bound, calls the
   update JS through `_safe` (errors swallowed and logged).
5. Bind the reporter to the page as soon as the page exists, and store it on the
   run record so later nodes/modules can fetch it from `browser_run_id`.
6. Unit-test the reporter with a fake page: assert the messages/actor, that a
   failing/absent page is swallowed, and that `clear()` removes the panel.

**Acceptance criteria**
- The panel renders once and updates in place (only the latest line); it never
  stacks.
- `step()` and `llm()` both print to the CLI and update the page when bound.
- A `None`/failing page never raises; the call is logged and the run continues.
- `clear()` removes the panel.
- Unit tests cover the reporter's message shape and error-swallowing.

**Notes**
- Proposed new module file: `src/tools/linkedin_status_overlay.py` (ask the
  human before creating the file name). Proposed test file:
  `tests/unit/test_linkedin_status_overlay.py`.
- The panel keeps **only the current line** (no history): each update replaces
  the previous message.
- On every update the panel re-raises itself to the top of the browser's top
  layer (hide + re-show its popover) so it stays in front of LinkedIn's Easy
  Apply modal, whose backdrop would otherwise cover a popover opened earlier.
- Keep the CLI path byte-identical in behaviour: the same text still reaches
  `print`, so existing logs/tests are unaffected.

## Subtask 9.2 — Instrument the agent/browser steps (Tasks 1-8)

**Status:** ✅ Done

**Goal:** Push a plain-language "Please wait — …" status for every major agent
step, so the human can follow the run end to end on the LinkedIn page.

**Preconditions**
- Subtask 9.1 provides the reporter, bound to the live page and reachable from
  `browser_run_id`.

**Inputs**
- The current step and its salient detail (search query, job index/title,
  company, page number, form step number, etc.).

**Steps**
1. Task 1 (login/search/filter — `linkedin_search.py`): status for opening
   LinkedIn / waiting for login, searching for `'<query>'`, and selecting the
   Easy Apply filter.
2. Task 2 (`linkedin_job_selection.py`): status for reading the job list,
   picking an Easy Apply job, and opening its form (include title/company when
   known).
3. Task 3 (`linkedin_best_matching_resume.py`): status for reading the job
   description; Task 3.1 status while waiting for the human's resume upload.
4. Task 4 (`linkedin_easy_apply_fill/`): status for enumerating the form,
   attaching the resume, advancing to the next step, and reaching the terminal
   step ("Waiting for you — review and submit…").
5. Task 5 (`linkedin_ask_human.py`): status while waiting for the human's answer
   to an unknown question.
6. Tasks 6-7 (`linkedin_skip_applied.py`, `linkedin_pagination.py`): status for
   skipping applied cards and moving to the next results page.
7. Task 8 (`linkedin_apply_loop.py`): status for waiting for the human's
   submission and opening the next unapplied job.
8. Leave the last meaningful status visible while the human owns the next action
   (e.g. "Waiting for you — review and submit…"); cleanup then removes the panel.

**Acceptance criteria**
- Each of the steps above produces a visible panel line during a live run.
- Messages are plain language and include the relevant detail (query, job,
  page, step).
- Wording is consistent ("Please wait — …" for agent work, "Waiting for you — …"
  while the human owns the action).

**Notes**
- Reuse each module's existing `notify` call sites where possible; route them
  through the reporter so the page updates too.
- Do not change automation behaviour — adding a status update must not alter
  any decision, click, or timing.

## Subtask 9.3 — Instrument the LLM steps (say exactly what the LLM is doing)

**Status:** ✅ Done

**Goal:** Whenever the LLM is invoked, the panel must state **exactly** what the
LLM is doing (and on which input) before the call, and what it decided after —
distinctly marked with an `LLM:` label.

**Preconditions**
- Subtask 9.1 provides `reporter.llm(action, detail)`.
- The LLM call sites are known: Task 3.2's describe/choose
  (`src/tools/resume_descriptions.py`, `_chat` at the describe and
  choose-best-resume calls) and Task 4.1's answer chooser
  (`src/tools/llm_answers.py`, `LLMAnswerChooser.__call__`).

**Inputs**
- The LLM action kind (describe a resume / choose the best resume / classify a
  question and choose an answer) and its input (resume file name; job title;
  question text + field type).
- The LLM's result (chosen resume + rationale; chosen answer + category;
  "unknown" when it cannot answer) and, when available, the model name.

**Steps**
1. Before each resume description: `LLM: summarizing resume '<file>' (i/N)…`.
2. Before matching: `LLM: choosing the best-matching resume for '<job title>'
   from N resumes…`; after: `LLM chose resume '<file>' — <rationale>.` or
   `LLM: no resume matched '<job title>'.`
3. Before each answer decision: `LLM: classifying the question '<question>' and
   choosing a stored answer…`; after: `LLM answered '<question>' → '<answer>'
   (<category>).` or `LLM: no confident answer for '<question>' — asking you.`
4. Pass the reporter into the LLM modules (via the caller), or expose a small
   optional `status` callback parameter, so they emit these messages without
   coupling the LLM modules to browser state.
5. Include the model name only (never the API key or raw request/response
   bodies that could contain secrets).

**Acceptance criteria**
- Every LLM call is announced before it happens, naming its input, with an
  explicit `LLM:` label.
- After the call, the panel shows the decision (or that it was unknown), and the
  same text is logged to the CLI.
- No secret (API key, token) is ever shown.
- Instrumentation never changes the LLM's decision or its error handling.

**Notes**
- Keep LLM modules decoupled: accept an optional status reporter/callback rather
  than importing browser state; the caller (the node/module with the run) wires
  the reporter in.
- When no reporter is supplied, behaviour is unchanged (pure CLI/no-op).
- Truncate long inputs (question/summary) sensibly so the panel stays readable.
