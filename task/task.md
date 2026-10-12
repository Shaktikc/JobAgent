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

**Status:** ✅ Done

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

---

## Task 4 — Open Easy Apply and start filling the application form

**Status:** 🟡 In progress — main flow done; Subtask 4.1 pending

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
6. Stop before the final **Submit application** action.

**Acceptance criteria**
- The Easy Apply form is open and its fields are enumerated.
- The resume from Task 3 is attached: either selected from the form's existing
  resume list when its name matches, or uploaded when it is not already listed.
- The matching listed resume is preferred over uploading a duplicate.
- Every field with a known answer is filled.
- Unknown fields are left for Task 5 (or flagged) rather than guessed.
- The application is **not** submitted.

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
