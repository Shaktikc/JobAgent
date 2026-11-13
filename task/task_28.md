# Task 28 — Show the latest agent log line in the on-page status panel (no generic placeholder)

**Status:** ✅ Done

**Reported problem**

- The bottom-left status panel on the LinkedIn page shows only the generic
  heading **"JobAgent is working"** (or **"JobAgent - the LLM is working"**) while
  the run is actively doing work.
- The terminal shows a continuous log — for example
  `Task 2: job 10 is already applied; skipping.`,
  `Skipping job 10 - already applied.`, and
  `Please wait - opening job 10: Senior Software Engineer (Verified job)...` —
  but the panel does not show those lines.
- The panel currently updates only when code calls `StatusReporter.step()` or
  `.llm()`. Plain `notify(...)` / `reporter(...)` lines are deliberately
  CLI-only (`StatusReporter.__call__`), and many steps log through `notify`
  only. So the panel's current line is empty or stale while the terminal is
  full of activity.
- The user wants the panel to show the **latest log/message the agent is
  doing**, mirroring the newest terminal line — not the full log history.

**Goal**

- The panel body always shows the most recent human-readable log line emitted
  for the run, in the same order as the terminal.
- Every runtime line that appears in the terminal while a live page exists also
  becomes the panel's latest line (technical `notify`, `step`, `llm`, and
  waiting-for-human messages).
- The panel must never sit on a generic-only message while a newer log line
  exists.
- Keep only the latest line (replace in place, no history, no stacked panels).

**Scope**

- Panel display, the `StatusReporter` plumbing, and any runtime call site that
  still bypasses the reporter with raw `print`.
- No change to automation decisions, clicks, timing, or the exact CLI text.
- No scrolling log/history in the panel; one latest line only.
- Startup/summary `print` lines outside the live browser run are out of scope.

**Preconditions**

- Task 9 is complete: `StatusReporter`, the `autojob-status` panel,
  `_UPDATE_STATUS_JS`, `_CLEAR_STATUS_JS`, and `get_reporter(run_id)` exist.
- The run registry stores the reporter for the live page
  (`src/tools/browser/runs.py`).

**Inputs**

- Every runtime `notify`/`progress` string (technical, step, LLM, waiting).
- The actor (`agent`, `llm`, and optionally `waiting`).
- The live page for the run, resolved from `browser_run_id`.

**Steps**

1. **Mirror the CLI callback into the panel.**
   - Change `StatusReporter.__call__` so it still calls `self.emit(message)` and
     additionally updates the panel with the same message (subject to the
     sanitization below).
   - Keep `step()` and `llm()` behaviour: they print and update the panel, with
     the LLM line marked as LLM.
   - Keep `emit_step` / `emit_llm` working when given a plain callable (CLI
     only, no page).
   - Do not change the text passed to `emit`/`print`; the terminal output must
     stay byte-identical.

2. **Sanitize the panel text.**
   - Collapse every newline, tab, and run of whitespace into a single space, then
     trim. Some `notify` messages are multi-line.
   - Cap the panel line at a readable length (for example 280 characters) and
     append an ellipsis; the full text still goes to the terminal.
   - Set the text with `textContent` only — never `innerHTML`.
   - Never expose secrets. Add a small redaction guard for obvious credential
     shapes (API keys/tokens such as `sk-...`, `Bearer ...`, long hex/base64
     blobs) and unit-test it.

3. **Serialize and coalesce panel updates so the latest line wins.**
   - Today `_schedule` creates one fire-and-forget task per message. Under rapid
     logging those tasks can finish out of order or pile up, so an older line
     could overwrite a newer one.
   - Keep one pending `(actor, message)` value and one pump task. The pump takes
     the latest pending value, evaluates it, and repeats until nothing is
     pending. Intermediate lines may be skipped; the final rendered line must
     always be the newest.
   - On `clear()`, cancel/await the pump and clear any pending value so a late
     update cannot recreate the panel after cleanup.
   - Keep every failure swallowed; the panel is best-effort and must never
     block or fail the run.

4. **Render the latest line when the page binds.**
   - Remember the last emitted `(actor, message)` on the reporter.
   - In `bind_page`, if a message was already emitted before the page existed,
     render it immediately so the panel is never created empty.
   - If no message has ever been emitted, do not create the panel just by
     binding; the first message creates it.

5. **Update the panel JS and heading.**
   - Keep the existing element ids (`autojob-status`,
     `autojob-status-heading`, `autojob-status-current`).
   - The heading is a compact label, not the status itself: for example
     **"JobAgent — latest activity"** for agent lines and
     **"JobAgent — the LLM is working"** for LLM lines.
   - The body always shows the latest log line. The generic
     "JobAgent is working" text may remain only as a fallback when no message
     exists yet; it must never be the only visible text while a newer line
     exists.
   - Detect lines beginning with `Waiting for you` and give them a distinct
     waiting style/heading (for example an amber border) so the human knows the
     agent is idle.
   - Keep the LLM purple styling.
   - Preserve the existing safety properties: `pointer-events:none`, top-layer
     re-raise on every update, `aria-live`, fixed bottom-left position, and
     in-place updates (never stack).
   - Keep long lines readable (wrap, and bound the panel height/width).

6. **Route every live-page runtime log through the reporter.**
   - Audit runtime call sites that pass `progress=print` or `notify=print`
     while a live page exists. At minimum:
     - `src/nodes/cleanup.py` — `release_run(..., progress=print)` should use
       `get_reporter(run_id) or print` so the final handoff line reaches the
       panel before cleanup.
     - `src/nodes/browse.py` — `start_tasks(progress=print, ...)` is wrapped in
       a `StatusReporter` inside `start_tasks`; confirm the panel still updates
       and leave the CLI output unchanged.
     - `src/tools/browser/runs.py` — `wait_for_human_close` / `release_run`
       must receive the run's reporter when one exists.
   - Review the self-heal paths: a reopened browser gets a new reporter bound to
     the new page, and the latest line must render on that new page.
   - Do not change any automation decision, click, or timing.

7. **Update and extend the tests.**
   - Replace `test_call_is_cli_only_not_the_panel` with a test proving a
     technical `notify` line both prints and becomes the panel's latest line
     (actor `agent`).
   - Add tests for:
     - multiline/whitespace collapsing and length truncation;
     - redaction of credential-shaped text;
     - rapid updates coalescing, with the last message winning;
     - identical consecutive messages not being re-rendered needlessly;
     - `clear()` cancelling pending updates and preventing panel recreation;
     - `bind_page` rendering a message emitted before the page existed;
     - a failing or absent page being swallowed (CLI still works);
     - `step`/`llm` still setting the correct actor and text.
   - Update any test that asserts the old CLI-only behaviour, including fakes
     that count `page.evaluate` calls.

8. **Update documentation.**
   - Update `README.md` (the live status panel description) to say the panel
     shows the **latest agent/LLM log line**, not just a generic status.
   - Task 28 supersedes Task 9's "technical detail does not clutter the panel"
     rule. Do not edit `task/task_9.md` unless the human explicitly approves it;
     record the supersession here instead.

9. **Live browser verification (required).**
   - Run a real flow (`uv run autojob --no-dry-run` or the existing live
     harness) and watch the panel while the terminal logs:
     - `Task 2: job N is already applied; skipping.` appears in the panel when
       that line prints.
     - `Please wait - opening job N: <title>...` appears in the panel when that
       line prints.
     - LLM lines appear with the LLM label/styling.
     - The waiting-for-human line appears when the agent is idle.
   - Confirm the panel never stays on a generic heading with no latest line
     while the terminal is logging.
   - Compare the DOM text
     (`document.getElementById('autojob-status-current').textContent`) with the
     last terminal line and capture a screenshot as evidence.
   - Never click **Submit application**. Leave the browser open per the existing
     rules.

**Acceptance criteria**

- Every runtime log line that appears in the terminal while a live page exists
  also becomes the panel's latest line (same text, modulo whitespace collapsing
  and truncation).
- The panel never shows only "JobAgent is working" while a newer log line
  exists.
- The panel shows the newest line even under rapid updates; a stale older line
  never overwrites a newer one.
- LLM lines keep the LLM label/styling; waiting-for-human lines are
  distinguishable.
- The panel updates in place (no stacking, no history) and long/multiline logs
  stay readable.
- No secrets ever appear in the panel.
- A failing or absent page never raises or blocks; CLI output is unchanged.
- Cleanup removes the panel and no pending update can bring it back.
- Relevant unit tests and a live-browser check pass. A passing unit test alone
  does not complete this task.
- The task is marked 🟡 **In progress** when work begins and stays so until the
  user explicitly confirms it works.

**Implementation notes**

- Primary files: `src/tools/linkedin_status_overlay/status_reporter.py`,
  `src/tools/linkedin_status_overlay/panel_js.py`,
  `src/tools/linkedin_status_overlay/__init__.py` (re-export any new helper),
  `tests/unit/test_linkedin_status_overlay.py`, `src/nodes/cleanup.py`,
  `src/nodes/browse.py`, `src/tools/browser/runs.py`, and `README.md`.
- Keep every file under the 415-line limit; split a module if it grows past it.
- Keep the reporter callable so existing `progress`/`notify` fakes and tests
  keep working.
- Put the sanitization/redaction logic in a small pure helper so it is easy to
  unit-test.
- Review interrelated code when implementing: every `notify` caller that can
  run with a live page, the self-heal reopen path, cleanup/release, and the
  panel tests.
- If live verification reveals a real defect (for example the panel was not
  updating because `__call__` was CLI-only, updates finished out of order, or a
  pending update recreated the panel after cleanup), log it in
  `known Bugs/task_28_bugs.md` and add/update the row in
  `known Bugs/bug_log.md` with symptom, root cause, fix, status, and evidence.
  Create the file without waiting for approval.
- Mark Task 28 ✅ **Done** in this file and `task/task.md` only after the
  implementation works, the live-browser check passes, and the user explicitly
  confirms it.
