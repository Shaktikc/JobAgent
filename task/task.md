# Tasks

## Task 1 — Log in to LinkedIn, search "software engineer", select Easy Apply

**Status:** ✅ Done

**Goal:** Launch the browser, open the LinkedIn login page, wait for the user to
log in successfully, search for **"software engineer"** jobs, and select the
**Easy Apply** filter.

**Inputs**
- `url` — `https://www.linkedin.com/login/`
- `search_query` — `software engineer`

**Steps**
1. Open the browser session.
2. Navigate to `https://www.linkedin.com/login/`.
3. Check whether the user is logged in.
4. **If NOT logged in:** wait for the user to log in (do not proceed until login
   is successful). Then continue to step 5.
5. **If logged in:** proceed directly to step 6.
6. Confirm login succeeded (e.g. the LinkedIn feed/home page is visible).
7. Type "software engineer" into the jobs search bar and submit it. Searching
   follows LinkedIn's normal behavior and may reload or navigate the page.
8. After the search returns results, click the **"Try AI job Search"** button
   **if it is present** (it is optional); when it is absent, continue unchanged.
9. After clicking **"Try AI job Search"**, **repeat the job search** (type
   "software engineer" into the search bar and submit again). 
10. Select the **Easy Apply** filter.

**Acceptance criteria**
- Browser opens successfully.
- LinkedIn login page loads.
- User logs in successfully.
- **"software engineer"** is typed into the jobs search bar and the search
  returns job results.
- The **"Try AI job Search"** button is clicked when present, and the
  "software engineer" search is performed **again** after each click while the
  button reappears (capped); absence of the button does not fail the run and then
  the search is performed only once.
- The **Easy Apply** filter is selected.



---

## Task 2 — Select Easy Apply from the job list

**Status:** ✅ Done

**Goal:** From the list of jobs seen after Task 1, select a job's **Easy Apply**
button.

**Preconditions**
- Task 1 is complete: user is logged in, "software engineer" jobs are shown, and
  the **Easy Apply** filter is selected.

**Inputs**
- None (uses the job list from Task 1).

**Steps**
1. Read the list of jobs currently displayed in the search results.
2. Pick a job from the list (the first / next unprocessed one).
3. Locate that job's **Easy Apply** button.
4. Click the **Easy Apply** button.
5. Confirm the Easy Apply flow/application form opened.

**Acceptance criteria**
- A job from the list is selected.
- The **Easy Apply** button is found and clicked.
- The Easy Apply application form/modal is visible after the click.

**Notes**
- If a job has no **Easy Apply** button, skip it and move to the next job.
- If the button is not found, capture a screenshot and the page URL for debugging.

---

## Task 3 — Read the job description and pick the best-matching resume

**Status:** 🟡 In progress — main flow done; Subtasks 3.1–3.2 pending

**Goal:** Read the description of the job that is open in the details pane, then
choose the resume from the `resumes/` folder that best fits that description.

**Preconditions**
- Task 2 is complete: a job is open and its **Easy Apply** form has been reached.
- The `resumes/` folder contains one or more candidate resumes (supported
  formats: `.pdf`, `.docx`, `.txt`, `.md`).

**Inputs**
- `resumes_dir` — path to the resumes folder (default `resumes/`).
- The job description text read from the open job's details pane.

**Steps**
1. Read the job description from the open job (title, company, location, and the
   full description body).
2. List the files in `resumes/`.
3. If the folder is empty, stop and report that no resumes are available.
4. Extract the readable text of each resume.
5. Compare each resume against the job description and score the fit (e.g. shared
   skills, titles, seniority, technologies, and years of experience).
6. Select the resume with the highest fit score.
7. Record the selected file path and a short reason for the choice.

**Acceptance criteria**
- The job description is read successfully.
- Every resume in `resumes/` is considered.
- Exactly one resume is selected as the best match.
- The chosen resume path and the matching rationale are recorded in the run
  state/log.

**Notes**
- Scoring may be deterministic keyword/weight matching or an LLM call, but the
  choice must be explainable (the rationale is stored).
- Do not rename, move, or modify the resume files.
- If two resumes tie, prefer the most recently modified file and note the tie.
- Subtask 3.2: when a resume has a stored description, score the job against that
  description instead of the full file text; the selected resume is what Task 4
  attaches/uploads.

### Subtask 3.1 — Ask the human for a resume when nothing matches, and remember it

**Status:** 🟡 In progress — implemented; pending review

**Goal:** When no resume in `resumes/` matches the open job's description at all,
pause and ask the human to upload a resume in the browser. Store the uploaded
file in the resumes pool and remember which *kind* of job it was provided for, so
a later similar job reuses it automatically instead of asking again.

**Preconditions**
- Task 3 is in progress: the job description has been read and the resumes scored.
- Task 2 is complete: the Easy Apply form is open and the browser session is live.
- The human is available to answer (see `AUTOJOB_SESSION_ASK_HUMAN`).

**Inputs**
- The scored candidates and the best fit score, with `AUTOJOB_RESUME_MIN_SCORE`
  (default `0`) deciding what counts as "no match at all".
- The remembered-resume library (`data/resume_library.json`).
- The resume the human uploads in the browser banner (`.pdf`, `.docx`, `.txt`, `.md`).

**Steps**
1. After scoring every resume, decide whether the job matched: the best score must
   be above `AUTOJOB_RESUME_MIN_SCORE`; an empty or unreadable pool counts as no
   match.
2. If no resume matched, first look in the remembered-resume library for a resume
   provided earlier for a **similar** job (overlapping skills, title words, and
   seniority). If one is found and its file still exists, reuse it and stop.
3. Otherwise, when asking is enabled, show a browser banner with a file picker and
   pause; read the file the human uploads and confirm the upload finished.
4. Validate (supported format, non-empty) and store the uploaded resume in the
   resumes pool without overwriting an existing file, then remember
   `job profile → resume` in the library.
5. Use that resume for this job (Task 4 attaches it) and for later similar jobs.
6. If the human skips, times out, or asking is off, record it and leave the normal
   error path in place rather than applying with no resume.

**Acceptance criteria**
- A job that shares no signal with any resume is detected as "no match".
- The human is prompted in the browser and the uploaded resume is stored in the pool.
- The uploaded resume's job profile is remembered, and a later similar job reuses
  it without asking again.
- Resume files already in the pool are never overwritten or modified.
- If the human does not provide a resume, the run fails cleanly instead of applying
  with no resume.

**Notes**
- The "similar job" test is explainable and deterministic (shared skills, title
  words, seniority) — no LLM is involved.
- The uploaded file is checked by extension and non-empty content before storage.
- The library holds job profiles and resume paths only; it never contains credentials.
- This subtask does **not** submit the application.

### Subtask 3.2 — Summarize an uploaded resume and match jobs against that summary

**Status:** ⬜ Not started

**Goal:** Whenever a new resume enters the pool (in particular the resume the human
uploads in Subtask 3.1), use the **LLM** to create a short description of it and
map that description to the resume file. Job matching then scores the open job
description against each resume's stored description — instead of re-extracting and
comparing the whole file every time — and the best-matching resume is the one
handed to Task 4 to attach/upload.

**Preconditions**
- Task 3 is in progress: the job description has been read.
- A resume was just added to the pool (uploaded by the human in Subtask 3.1, or
  otherwise newly placed in `resumes/`) and has no stored description yet.
- The LLM is configured (`OPENROUTER_API_KEY` + `AUTOJOB_LLM_MODEL`); if it is not,
  raise an error and stop instead of describing the resume another way.

**Inputs**
- The newly stored resume file and its extracted text (`extract_resume_text`).
- The LLM client built from `LLMSettings` (same OpenRouter/OpenAI-compatible model
  as Task 4.1).
- The resume-description map (`data/resume_descriptions.json`), keyed by the
  canonical resume file path.

**Steps**
1. When a resume is added to the pool, extract its readable text
   (`extract_resume_text`).
2. Confirm the LLM is configured; if it is not, record an error and stop before
   matching — there is no fallback description.
3. Ask the **LLM** for a short, structured description of that resume: a one-line
   summary plus its skills/technologies, likely title(s), seniority, years of
   experience, and the domain/industry. The model must summarise only what is in
   the resume — never invent experience or credentials.
4. If the LLM call fails or returns an unusable reply, record an error and stop;
   do not substitute a deterministic description.
5. Parse the model's reply into the same compact fields the deterministic matching
   uses, so the description can be scored by `score_resume`.
6. Map the description to the resume file in the resume-description store, keyed by
   the resume's canonical path; update the entry when the same file is
   re-described so no duplicate entries pile up.
7. Never rename, move, or modify the resume file — only the sidecar store changes.
8. When scoring resumes for a job (Task 3's `select_best_resume`), score the job
   description against each resume's stored LLM description, reusing the existing
   weighted scorer (`score_resume`) so the result stays explainable. If a resume has
   no stored description, record an error and stop — do **not** score its raw text.
9. Refresh the stored description only when the resume file changed (its mtime or
   size differs from what was recorded).
10. Select the highest-scoring resume as the best match and record the rationale
    (as Task 3 already does); Task 4 then attaches/uploads that chosen resume.

**Acceptance criteria**
- A newly uploaded resume gets a short description produced by the LLM, stored and
  mapped to its file.
- The LLM description is validated/normalised into the fields the scorer uses, and
  the raw resume text still round-trips (the model summarises, it does not invent).
- On later jobs the stored description is reused, so the resume is not re-extracted
  or re-summarised to rebuild the description.
- Job matching scores the job description against the resume description and
  selects the best-matching resume.
- Every resume considered for a job has an LLM description; a resume without one is
  an error, not scored from its raw text.
- Re-describing the same file updates its entry instead of creating a duplicate.
- If the LLM is not configured, or the call fails or returns an unusable reply, an
  error is recorded and the run stops cleanly — no deterministic fallback is used.
- Resume files are never modified, renamed, or moved.
- The chosen resume's path and matching rationale are recorded, and the selected
  resume is the one Task 4 attaches/uploads.

**Notes**
- The short description is generated by the **LLM** (same configured model as
  Task 4.1, temperature 0) from the raw resume text. There is **no deterministic
  fallback**: if the LLM is unconfigured, errors, or returns an unusable reply, the
  subtask records an error and stops rather than describing the resume another way.
- Matching uses only the stored LLM description. A resume with no stored description
  is an error rather than being scored from its raw text.
- The LLM only summarises the resume it is given — it must not add skills, titles,
  or years that are not present in the file.
- The store maps resume path → description (plus the file's mtime/size) and never
  contains credentials.
- Uploading/attaching the resume is still Task 4's job; this subtask only chooses
  the resume using its description.
- Depends on Subtask 3.1: the human-uploaded resume is the main source of new
  resumes, so describing it at upload time is the natural hook.

---

## Task 4 — Open Easy Apply and start filling the application form

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

### Subtask 4.1 — LLM decides the answer for each question

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

### Subtask 4.2 — Leave the browser open at the last step and wait for the human

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

---

## Task 5 — Ask the human for unknown answers, remember them, and show UI feedback

**Status:** ✅ Done

**Goal:** When the form asks a question the agent cannot answer with confidence,
pause and wait for the human's answer. Store the answer in the answer store so
Task 4's LLM can reuse it on a later run. While waiting, show a feedback message
in the browser UI saying that the agent does not know the answer.

**Preconditions**
- Task 4 is in progress: the Easy Apply form is open and being filled.
- A writable answer store is available (e.g. `data/answers.json`).

**Inputs**
- The unknown question text (label, help text, and field type).
- The human's answer (entered interactively).

**Steps**
1. Detect a form question the agent cannot answer with confidence (the Task 4
   LLM could not decide it from the store, so the answer is unknown).
2. Show a feedback message in the browser UI stating that the agent does not know
   the answer (e.g. a visible banner/overlay near the field or modal).
3. Pause the run and wait for the human to provide the answer.
4. On receiving the answer, fill the field.
5. Save the question → answer mapping to the answer store.
6. Repeat for each subsequent unknown question.
7. Continue filling the form until all questions are answered or the run is
   stopped.

**Acceptance criteria**
- Unknown questions pause the run and wait for human input.
- A browser-UI feedback message clearly says the agent does not know the answer.
- The human's answer is stored, mapped to the question.
- When the same question later appears, Task 4's LLM answers it from the store
  with no further prompting.
- The answer store persists across runs.

**Notes**
- Store each answer against its question; Task 4's LLM matches questions by
  meaning, so an exact key wording is not required.
- Never overwrite an existing mapping silently; if the human changes an answer,
  record the update explicitly.
- The store must not contain credentials or other secrets.
- This task does **not** submit the application.

---

## Task 6 — Skip jobs already marked "Applied" and open the next unapplied job

**Status:** ✅ Done

**Goal:** When reading the job list on the current results page, detect the jobs
the user has already applied to (their card shows an **"Applied"** status, e.g.
"Applied · 5 months ago"), skip them, and open the **next job that has not been
applied to**.

**Preconditions**
- Task 1 is complete: "software engineer" jobs are shown with the **Easy Apply**
  filter selected.
- Task 2 selects a job from that list; this task changes *which* job it selects.

**Inputs**
- The job cards currently displayed in the search-results list.
- Optional setting (if added): `AUTOJOB_SESSION_SKIP_APPLIED` (default on) to
  toggle the skip behaviour.

**Steps**
1. Read the job cards from the results list.
2. For each card, read its status line (the area that shows
   "Applied · 5 months ago", "Viewed · 2 weeks ago", or the Easy Apply badge).
3. Detect the **applied** marker on the card: the status text contains the word
   **"Applied"** (case-insensitive). Do not confuse it with other statuses such
   as "Viewed", "Saved", or a control named "Easy Apply".
4. Skip every card whose status is **Applied** without clicking it.
5. Open the **first card that is not Applied** (and still offers Easy Apply),
   and continue the existing Task 2 flow (click Easy Apply → wait for the form).
6. If **every** card on this page is Applied, do **not** open any job; stop
   gracefully with a clear note that no unapplied job was found on this page
   (Task 7 covers moving to the next results page).

**Acceptance criteria**
- A job card showing an **"Applied"** status is detected and skipped.
- The job that is opened is the first card whose status is **not Applied**.
- Skipping a card does not click it (no application form is opened for an
  applied job).
- If every job on the page is Applied, the run stops with a clear note and opens
  nothing on that page.
- Detection does **not** regress the existing "no Easy Apply → skip" behaviour:
  non-applied jobs without Easy Apply are still skipped.

**Notes**
- The status text lives **inside the job card** (the results list item), separate
  from the details pane; read it from the card, not from the details pane.
- **This is a dynamic list:** the status label's markup/position varies, so match
  on the normalized card text (trim, lowercase, collapse whitespace) rather than
  a fixed selector.
- Prefer a focused, explainable helper (e.g. `card_is_applied(text)`) so the rule
  is unit-testable and recorded in the outcome.
- Record which cards were skipped as applied (index/title) and expose a count on
  `Task2Outcome` (e.g. `applied_jobs_skipped`) for the log/summary.
- Ignore the `5 months ago` / `2 weeks ago` age text when classifying; only the
  **Applied** status word decides.
- If no status can be read from a card, do not assume it is Applied — treat it as
  unapplied and let the existing Easy Apply check decide.
- Never click Submit; submission stays a manual human step.

---

## Task 7 — When every job on the page is "Applied", go to the next results page

**Status:** ⬜ Not started

**Goal:** When **every** job on the current results page is already marked
**"Applied"** (Task 7 found no unapplied job), move to the **next results page**
using the pagination controls and keep looking, until an unapplied job is found
or there are no more pages.

**Preconditions**
- Task 7 is complete on the current page: every card is Applied and no job was
  opened.
- The results list is paginated (page numbers `1 2 3 …` with a **Next** button
  below the list).

**Inputs**
- The results pagination controls (page numbers and the **Next** / **Previous**
  buttons) below the job list.
- The current page number (to detect that the page actually advanced).

**Steps**
1. On the results page where Task 7 found every card Applied, locate the
   pagination controls below the job list.
2. Determine whether there is a next page: the **Next** button is enabled, or a
   higher page number exists.
3. If a next page exists, click **Next** (or the next page number) and wait for
   the new page of job cards to load.
4. Re-run Task 7's logic on the new page: skip the Applied cards and open the
   first unapplied job.
5. Repeat steps 1–4 for each subsequent page: only paginate again when the whole
   page is Applied.
6. Stop paginating when:
   - an unapplied job is opened (Task 7 resumes normally), or
   - the **Next** button is disabled/absent (last page), or
   - the page number no longer changes after a click (pagination is stuck), or
   - the safety cap of visited pages is reached.
7. If every job on every page is Applied, stop gracefully with a clear note that
   no unapplied jobs were found across the pages searched, and open nothing.

**Acceptance criteria**
- When every card on the current page is Applied, the next results page is
  opened automatically.
- After paginating, Task 7's skip logic runs again on the new page's cards.
- Pagination stops at the last page (Next disabled/absent), when pagination is
  stuck, or after the safety cap.
- The number of pages visited is recorded in the outcome/log.
- If all jobs on all pages are Applied, the run stops with a clear note and opens
  nothing.
- Going to the next page never opens or applies to a job by itself.

**Notes**
- **Pagination is dynamic:** discover the controls at runtime rather than
  assuming a selector. The list shows page numbers plus **Next** (and often
  **Previous**).
- Detect "last page" by the **Next** control being disabled, absent, or by the
  page number/content not changing after a click.
- Advancing a page must **not** be mistaken for opening a job: after paginating,
  re-read the cards and re-check their statuses instead of carrying over the
  previous page's decision.
- Cap pagination (e.g. `_MAX_RESULT_PAGES`) so a control that never disables can
  never loop forever, consistent with the existing click caps.
- Record the number of results pages visited (e.g. `pages_visited`) on
  `Task2Outcome` for the log/summary.
- If the pagination controls cannot be found, stop gracefully with a clear note
  instead of retrying blindly.
- Never click Submit; submission stays a manual human step.
