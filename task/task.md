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
7. Open the jobs search tab and **type "software engineer" into the search bar**,
   then submit the search.
8. Open the search results and select the **Easy Apply** filter.

**Acceptance criteria**
- Browser opens successfully.
- LinkedIn login page loads.
- User logs in successfully.
- **"software engineer"** is typed into the jobs search bar and the search
  returns job results.
- The **Easy Apply** filter is selected.

**Notes**
- Browser automation is opt-in (`AUTOJOB_*` settings, `--dry-run` off).
- The query must be entered through the jobs search bar (typed in), not by
  navigating to a search URL.
- **Login gate:** if the user is not logged in, pause and wait for the user to
  log in. Only once login is successful do the remaining steps (search
  "software engineer" → select Easy Apply).
- If the search or filter is not found, capture a screenshot and the page URL for debugging.

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

---

## Task 5 — Ask the human for unknown answers, remember them, and show UI feedback

**Status:** ⬜ Not started

**Goal:** When the form asks a question the agent cannot answer with confidence,
pause and wait for the human's answer. Store the answer keyed by the question so
the same question is answered automatically next time. While waiting, show a
feedback message in the browser UI saying that the agent does not know the answer.

**Preconditions**
- Task 4 is in progress: the Easy Apply form is open and being filled.
- A writable answer store is available (e.g. `data/answers.json`).

**Inputs**
- The unknown question text (label, help text, and field type).
- The human's answer (entered interactively).
- Previously stored question → answer mappings.

**Steps**
1. Detect a form question the agent cannot answer with confidence.
2. Look the question up in the answer store (normalized key, ignoring
   whitespace/case).
3. **If a stored answer exists:** apply it automatically and continue — do not
   ask again.
4. **If no stored answer exists:**
   a. Show a feedback message in the browser UI stating that the agent does not
      know the answer (e.g. a visible banner/overlay near the field or modal).
   b. Pause the run and wait for the human to provide the answer.
   c. On receiving the answer, fill the field.
   d. Save the normalized question → answer mapping to the answer store.
5. Repeat for each subsequent unknown question.
6. Continue filling the form until all questions are answered or the run is
   stopped.

**Acceptance criteria**
- Unknown questions pause the run and wait for human input.
- A browser-UI feedback message clearly says the agent does not know the answer.
- The human's answer is stored, mapped to the question.
- When the same (normalized) question later appears, it is answered automatically
  from the store with no further prompting.
- The answer store persists across runs.

**Notes**
- Normalize keys (trim, lowercase, collapse whitespace) so near-identical
  questions reuse the stored answer.
- Never overwrite an existing mapping silently; if the human changes an answer,
  record the update explicitly.
- The store must not contain credentials or other secrets.
- This task does **not** submit the application.
