# Task 26 — Save an unknown answer only after the human finishes answering

**Status:** 🟡 In progress

**Goal:** When Task 5 asks the human to answer an unknown Easy Apply question, do
not persist, confirm, or use the answer while the human is still typing or still
choosing options. Save the answer only after the human explicitly finishes
(blur, Enter, or a **Done** control), and only then close the banner and let the
run continue. A partial value must never reach `data/answers.json` or be used to
fill the form.

**Reported problem**

- The agent shows the unknown-question banner and starts polling the form
  control.
- The current flow persists any non-empty value on the first poll
  (`_store_answer` is called before the reader's `done` flag is consulted), so
  the first few keystrokes of a text answer are written to the answer store, and
  each later keystroke overwrites the previous partial value.
- The run does not reliably wait for the human to finish: if the wait ends
  (timeout/skip/navigation) while the field holds an unfinished value, the last
  partial value can be returned and used, so the human has no time to type the
  answer properly.
- Observed requirement: "only after the user types the answer to the unknown
  question, then only save it."

**Preconditions**

- Task 5's banner and answer watcher exist
  (`src/tools/linkedin_ask_human/`).
- The answer is entered in the real form control; the banner has no free-text
  input.
- Submission remains a manual human action.

**Root cause in the current code**

- `src/tools/linkedin_ask_human/flow.py` calls `_store_answer(...)` as soon as a
  poll returns any non-empty `value`, without first requiring
  `answer_payload["done"]`.
- `src/tools/linkedin_ask_human/answer_js.py` records every `input` event in
  `state.value` but leaves `state.done` false until `change`/`focusout`/Enter.
  The flow ignores that distinction for persistence.
- The timeout path returns `last_saved` (a partial value captured mid-typing)
  instead of treating it as unfinished.
- `src/tools/linkedin_ask_human/store.py`'s early-save safety net therefore runs
  on partial input.

**Steps**

1. Define "finished answering" at runtime for each control kind:
   - **Text / textarea:** a `change` event, a `focusout` (blur), Enter, or an
     explicit **Done** control in the banner.
   - **`<select>` / radio / single checkbox:** a committed selection is atomic
     (`change`/click with a real value); never treat an open dropdown or a prompt
     option as finished (keep BUG-037 behaviour).
   - **Multi-select checkbox group:** all intended ticks are in place and the
     human confirms with **Done** (or the group is stable after a completion
     signal). Do not close the banner after an arbitrary short timer alone.
2. Add an explicit completion affordance to the banner: a **Done** button that
   becomes usable once a non-empty answer is detected. Clicking it marks the
   current form value as finished; it must not duplicate or replace the answer.
   Keep **Skip** for an intentional skip.
3. Change the wait loop so it never persists or reports an answer until the
   completion signal is present:
   - Keep polling the control so the banner/status reflects the live value.
   - Do not call `_store_answer` / `_remember_answer`, do not show the "Saved"
     confirmation, and do not return/advance on a value whose `done` is false.
   - Persist exactly once, with the final value, when finished; a later edit
     before completion must simply update the pending value, not the store.
4. Treat the configured `ask_timeout_seconds` as an **inactivity** timeout while
   the human is answering: reset/extend it when the human focuses the control,
   edits it, or ticks an option. Do not time out mid-typing merely because a
   fixed deadline elapsed.
5. On a real timeout (no interaction for the configured period) or a skip:
   - Never save or use a partial/unfinished value.
   - Leave the question unknown, record an honest note (e.g. "timed out waiting
     for you to finish"), and let the existing unknown/skip path continue. Do not
     pretend the question was answered.
6. For the pre-filled check (a value already on the form before polling starts):
   adopt it only when the control is actually committed/answered and not
   currently being edited. A focused text control with an unfinished value is
   not an answer.
7. Keep the existing guards: prompt options, question echoes, empty values, and
   stale values from another question's scope must still never be stored
   (BUG-037, BUG-082).
8. Add unit tests for the state machine: input-only values are not stored;
   blur/Enter/**Done** store the complete value exactly once; partial value +
   timeout stores nothing; multi-select ticks survive until **Done**; pre-filled
   committed controls are still adopted; Skip still discards.
9. Live-browser verification on a real LinkedIn Easy Apply text question: type a
   multi-word answer slowly (longer than `ask_poll_seconds`) and confirm
   `data/answers.json` contains no partial prefix during typing; finish with
   blur/Enter/**Done** and confirm the complete answer is saved once, the banner
   confirms, and the run continues.

**Acceptance criteria**

- While the human is typing, `data/answers.json` contains no entry for the
  question and the banner does not say "Saved".
- The answer is stored only after a clear completion signal (blur, Enter, or
  **Done**), exactly once and with the complete final value.
- A timeout or skip after partial typing leaves the question unanswered, stores
  nothing, and never feeds the partial value back into the form.
- The run waits while the human is actively answering; the timeout does not fire
  in the middle of typing.
- Multi-select answers are saved only after the human finishes selecting.
- Existing behaviour is preserved: prompt options and question echoes are never
  saved, a pre-filled committed answer is still accepted, Skip still works, and
  the store keeps its existing schema.
- Relevant automated tests cover partial typing, blur/Enter/**Done**, timeout,
  skip, pre-filled controls, single choice, and multi-select.
- Live-browser verification on LinkedIn confirms the reported problem is fixed;
  unit tests alone do not complete this task.

**Implementation notes**

- Start in `src/tools/linkedin_ask_human/flow.py` (wait loop / save gating),
  `src/tools/linkedin_ask_human/answer_js.py` (completion signal, inactivity
  activity), `src/tools/linkedin_ask_human/banner_js.py` (Done control/status),
  and `src/tools/linkedin_ask_human/store.py` (persist only on completion).
  Keep the package's public API re-exports in
  `src/tools/linkedin_ask_human/__init__.py` unchanged (or update every caller
  and lazy re-export in `src/tools/browser/task_exports.py`).
- Review interrelated code: `src/tools/linkedin_easy_apply_fill/form_walk.py`
  (caller), `src/tools/linkedin_status_overlay.py` (human turn/emit_step),
  `src/configuration.py` (`ask_timeout_seconds` / `ask_poll_seconds` semantics and
  docs), Task 5's outcome fields (`src/state/forms.py`), and all Task 5 tests,
  including `tests/unit/test_task5_form_answers.py`,
  `tests/unit/test_browser_tools/test_human_banner.py`,
  `tests/unit/test_browser_tools/test_human_answers.py`,
  `tests/integration/test_checkbox_group_live.py`, and
  `tests/integration/test_fill_form_live/test_banner.py`. Update every
  `monkeypatch` target that points at the moved/changed function.
- Do not grow any file past 415 lines; split by concern if needed (for example a
  completion-state helper module).
- Log any bug found/fixed while implementing this task in
  `known Bugs/task_26_bugs.md`, cross-reference the Task 5 defect in
  `known Bugs/task_5_bugs.md`, and update `known Bugs/bug_log.md` in the same
  change, with accurate status and evidence. Create the file without waiting for
  approval.
- Keep Task 26 🟡 In progress in this file and `task/task.md` while it is being
  worked on. Mark it ✅ Done only after implementation, live-browser
  verification, and the user's explicit confirmation that the task works.
