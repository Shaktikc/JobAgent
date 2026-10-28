# Task 4 — Open Easy Apply and start filling the application form

**Status:** ✅ Done

**Goal:** Open the Easy Apply form and begin filling it: attach the resume chosen
in Task 3 and populate every field whose answer is already known. Do **not**
submit the application.

**Preconditions**
- Task 2 is complete: the Easy Apply application form/modal is open.
- Task 3 is complete: a best-match resume has been selected.

**Inputs**
- The open Easy Apply form.
- The selected resume file from Task 3.
- Known profile/answer data (from settings, a profile file, or the answer store
  created in Task 5).

**Steps**
1. Enumerate the form's fields and controls (text inputs, selects, radio buttons,
   checkboxes, date pickers, and the resume upload control).
2. For each field, determine whether the answer is already known.
3. Fill the fields whose answers are known.
4. Attach the resume chosen in Task 3:
   a. Check the resume options already listed on the form (e.g. LinkedIn's
      "Select a resume" list).
   b. **If the chosen resume's name matches one already listed on the form,**
      select that listed resume directly — do **not** upload the file again.
   c. Otherwise, upload the resume file through the resume/attachment control.
5. Advance through multi-step forms as needed, continuing to fill known fields.
6. Stop before the final **Submit application** action. When the terminal step is
   reached, **leave the browser open** and wait for the human to review, submit,
   and close the window themselves (see Subtask 4.2).

**Acceptance criteria**
- The Easy Apply form is open and its fields are enumerated.
- The resume from Task 3 is attached: either selected from the form's existing
  resume list when its name matches, or uploaded when it is not already listed.
- The matching listed resume is preferred over uploading a duplicate.
- Every field with a known answer is filled.
- Unknown fields are left for Task 5 (or flagged) rather than guessed.
- The application is **not** submitted.
- At the terminal step (only **Submit application** remains) the browser is left
  open and the run waits for the human to close it — it is never closed
  automatically before that.

**Notes**
- Never type credentials; the login gate remains human.
- Resume matching is by name: compare the Task 3 file name (without extension,
  normalized) against the names shown in the form's resume list. When a match is
  found, select it instead of uploading, so no duplicate resume is created.
- Only upload the file when no listed resume matches.
- If a field cannot be found or filled, capture a screenshot and the page URL for
  debugging.
- Never click **Submit application** — submission stays a manual human step.

## Subtask 4.1 — LLM decides the answer for each question

**Status:** ✅ Done

**Goal:** While filling the form, for every question the LLM first reads the
question to determine **what kind of question it is**, then consults the answer
store (`data/answers.json`), and then decides **which stored answer is
appropriate** for that question. Only when no stored answer fits does the
question become unknown and get handed to **Task 5**.

**Preconditions**
- Task 4 is in progress: the Easy Apply form is open and its fields are
  enumerated.
- An answer store is available (`data/answers.json`, via
  `src.tools.answers.load_answers`).

**Inputs**
- Each field's question context: label, help/placeholder text, field type
  (text, select, radio, checkbox, date), and its available options.
- The answer store entries (normalized question → answer).
- An LLM client (text model) used to classify the question and choose the answer.

**Steps**
1. For each enumerated field, build the question context (label, help text, field
   type, and option labels).
2. Ask the LLM to **classify what kind of question it is** (for example: years of
   experience, salary expectation, work authorization, notice period, a yes/no
   question, a location/relocation question, etc.).
3. Pass the answer store's question → answer entries to the LLM together with the
   question context.
4. Ask the LLM to **decide which stored answer is appropriate** for the given
   question by matching on meaning. It returns either a chosen stored answer
   (with the matching key and a short rationale) or "unknown".
5. **If the LLM chooses an answer:** fill the field with it and record the decision
   (question, chosen key, rationale) in the run state/log.
6. **If the LLM returns "unknown"** (no stored answer fits, or it cannot answer
   with confidence): do **not** guess — leave the field for **Task 5** to ask the
   human and remember the answer.
7. Repeat for each field; never overwrite an existing mapping silently, and never
   click **Submit application**.

**Acceptance criteria**
- Every question is classified by the LLM before it is answered.
- The LLM is shown the answer store and decides the appropriate answer for the
  question.
- A stored answer is reused even when the wording differs but the meaning matches.
- Questions with no matching/confident answer are deferred to **Task 5** as
  unknown rather than guessed.
- Each decision is explainable and recorded (chosen key + rationale).
- The application is **not** submitted.

**Notes**
- The LLM decision is the **only** answering path — there is no deterministic
  exact-key lookup fallback. The LLM reads the answer store and chooses the
  answer itself.
- If the LLM cannot choose a stored answer (no match, or low confidence), the
  question is treated as unknown and handed to **Task 5**.
- The store and the LLM prompt must not contain credentials or other secrets.
- This subtask does **not** submit the application.

## Subtask 4.2 — Leave the browser open at the last step and wait for the human

**Status:** 🟡 In progress — implemented; pending review

**Goal:** When the Easy Apply walk reaches its **terminal step** (only the
**Submit application** button remains), do **not** close the browser. Keep the
window open so the human can review and submit the application manually, and make
the run wait until the human closes the browser window themselves.

**Preconditions**
- Task 4 is in progress: the Easy Apply form is open and being walked step by step.
- The terminal step has been detected: there is no enabled Next/Continue control
  and no disabled next-like control (the only action left is **Submit
  application**).

**Inputs**
- The Task 4 outcome flag that records the walk stopped at the terminal step.
- The live browser session (kept open by the ``browse`` node).
- `AUTOJOB_SESSION_KEEP_OPEN_TIMEOUT_SECONDS` (default `1800`, `0` = wait
  indefinitely) and `AUTOJOB_SESSION_KEEP_OPEN_POLL_SECONDS` (default `1.0`).

**Steps**
1. When the walk stops with only **Submit application** remaining, mark the Task 4
   outcome as having reached the terminal step.
2. In the ``cleanup`` node, if that flag is set and the application was not
   submitted, **do not** close the session: leave the window open for the human.
3. Wait for the human to close the browser window: poll the session's live CDP
   connection until it drops, up to `AUTOJOB_SESSION_KEEP_OPEN_TIMEOUT_SECONDS`.
4. When the human closes the window, forget the session and finish the run
   normally (verify/summary).
5. If the wait times out (a positive `AUTOJOB_SESSION_KEEP_OPEN_TIMEOUT_SECONDS`
   elapsed), close the session for the human and record that the wait timed out in
   the log. A timeout of `0` waits indefinitely, so this branch never triggers.
6. On every other path (a fill failure, a matching failure, no terminal step),
   keep the existing behaviour: close the session so no Chromium window is left
   behind.

**Acceptance criteria**
- Reaching the terminal step leaves the browser open instead of closing it.
- The run waits for the human to close the window before finishing.
- The browser is never closed automatically while it is sitting on the last step
  (before the wait times out).
- A timeout closes the session and records that the wait timed out.
- Non-terminal paths still close the session as before.

**Notes**
- This subtask does **not** click **Submit application**; submission stays a
  manual human step. The human submits and closes the window when ready.
- The wait is bounded by `AUTOJOB_SESSION_KEEP_OPEN_TIMEOUT_SECONDS` so a window
  left open forever cannot hang the run indefinitely (set `0` to opt into waiting
  indefinitely).
- "Reached the last step" is an explicit outcome flag
  (`Task4Outcome.reached_terminal_step`), not a string match on the note.
- **Task 12 extension:** a free-text question about the current job/employer/role
  (or the applicant's fit) may instead be answered by the LLM from the current
  job description and the selected resume, with cited evidence. This wraps the
  Task 4.1/10 chooser; an exact human-confirmed store answer still wins, and a
  generated context answer is never written to `answers.json` or
  `derived_answers.json`.
