# Task 3 — Read the job description and pick the best-matching resume (LLM)

**Status:** ✅ Done

**Goal:** Read the description of the job that is open in the details pane, then
ask an LLM to choose the resume from the `resumes/` folder that best fits that
description. The LLM is the **only** matching path — there is no deterministic
scoring fallback.

**Task 16 note:** strict resume matching is the default. Only a candidate the LLM
rates `strong` proceeds; a no-match is a clean skip and the Subtask 3.1 fallbacks
below are **not** used. Set `AUTOJOB_SESSION_REQUIRE_RESUME_MATCH=false` to
restore them. See Task 16 for the gate.

**Implementation order (bottom-up, easy to test):**
Build and verify the pieces in this order, one slice at a time:
1. **Subtask 3.1** — Ask the human for a resume when nothing matches, and remember it.
2. **Subtask 3.2** — Describe each resume with the LLM and let the LLM pick the match.
3. **Main flow** (at the end of this file) — Read the job description and pick the
   best-matching resume (LLM), wiring 3.1 and 3.2 together into the end-to-end path.

**Preconditions**
- Task 2 is complete: a job is open and its **Easy Apply** form has been reached.
- The `resumes/` folder contains one or more candidate resumes (supported
  formats: `.pdf`, `.docx`, `.txt`, `.md`).
- An LLM client (text model) is configured (the same LLM settings as Task 4.1).

**Inputs**
- `resumes_dir` — path to the resumes folder (default `resumes/`).
- The job description text read from the open job's details pane.
- Each resume's stored LLM description (Subtask 3.2), used as the candidate's
  profile for matching.
- The LLM client used to choose the best match.

## Subtask 3.1 — Ask the human for a resume when nothing matches, and remember it

**Status:** ✅ Done

**Goal:** When no resume in `resumes/` matches the open job's description at all,
pause and ask the human to upload a resume in the browser. Store the uploaded
file in the resumes pool and remember which *kind* of job it was provided for, so
a later similar job reuses it automatically instead of asking again.

**Preconditions**
- Task 3 is in progress: the job description has been read and the LLM has chosen
  a resume (or answered **none**).
- Task 2 is complete: the Easy Apply form is open and the browser session is live.
- The human is available to answer (see `AUTOJOB_SESSION_ASK_HUMAN`).

**Inputs**
- The LLM's matching decision from Task 3 (chosen candidate + rationale, or
  **none**), which decides what counts as "no match at all".
- The remembered-resume library (`data/resume_library.json`).
- The resume the human uploads in the browser banner (`.pdf`, `.docx`, `.txt`, `.md`).

**Steps**
1. After the LLM chooses, decide whether the job matched: a valid chosen candidate
   means matched; the LLM answering **none** (or an empty/unreadable pool) counts as
   no match.
2. If no resume matched, first look in the remembered-resume library for a resume
   provided earlier for a **similar** job (overlapping skills, title words, and
   seniority). If one is found and its file still exists, reuse it and stop.
3. Otherwise, when asking is enabled, show a browser banner with a file picker and
   pause; read the file the human uploads and confirm the upload finished.
4. Validate (supported format, non-empty) and store the uploaded resume in the
   resumes pool without overwriting an existing file, then remember
   `job profile → resume` in the library.
5. Hand the stored resume to Subtask 3.2 so the **LLM** describes it and the
   description is stored. If the LLM is unconfigured or the description fails,
   record an error and stop — there is no fallback description.
6. Use that resume **directly** for this job (Task 4 attaches it) — do **not**
   re-run the match — and remember it for later similar jobs.
7. If the human skips, times out, or asking is off, record it and leave the normal
   error path in place rather than applying with no resume.

**Acceptance criteria**
- A job that shares no signal with any resume is detected as "no match".
- The human is prompted in the browser and the uploaded resume is stored in the pool.
- The uploaded resume is described by the **LLM** (Subtask 3.2) and its description
  is stored before the resume is used.
- The uploaded resume is used directly for the current job (Task 4 attaches it);
  the match is not re-run.
- The uploaded resume's job profile is remembered, and a later similar job reuses
  it without asking again.
- Resume files already in the pool are never overwritten or modified.
- If the human does not provide a resume, the run fails cleanly instead of applying
  with no resume.

**Notes**
- The "similar job" test is explainable and deterministic (shared skills, title
  words, seniority) — no LLM is involved.
- After a successful upload the flow is: store → Subtask 3.2 LLM description →
  use directly for this job. A missing/failed description is an error, not a reason
  to re-match or use the resume un-described.
- The uploaded file is checked by extension and non-empty content before storage.
- The library holds job profiles and resume paths only; it never contains credentials.
- This subtask does **not** submit the application.

## Subtask 3.2 — Describe each resume with the LLM and let the LLM pick the match

**Status:** ✅ Done

**Goal:** Keep a short, LLM-written description for every resume in the pool, and
have the **LLM** rate every candidate and choose the strongest match for a job
directly from those descriptions. There is no deterministic scorer anywhere in the
match.

**Preconditions**
- Task 3 is in progress: the job description has been read.
- A resume is in the pool (uploaded by the human in Subtask 3.1, or otherwise
  placed in `resumes/`) and has no stored description yet.
- The LLM is configured (`OPENROUTER_API_KEY` + `AUTOJOB_LLM_MODEL`); if it is not,
  raise an error and stop instead of matching another way.

**Inputs**
- The resume files and their extracted text (`extract_resume_text`).
- The LLM client built from `LLMSettings` (same OpenRouter/OpenAI-compatible model
  as Task 4.1).
- The resume-description map (`data/resume_descriptions.json`), keyed by the
  canonical resume file path.
- The open job description (Task 3).

**Steps**
1. When a resume is added to the pool, extract its readable text
   (`extract_resume_text`).
2. Confirm the LLM is configured; if it is not, record an error and stop before
   matching — there is no fallback description.
3. Ask the **LLM** for a short, structured description of that resume: a one-line
   summary plus its skills/technologies, likely title(s), seniority, years of
   experience, domain/industry, up to six factual highlights (leadership,
   architecture, platform/tooling, delivery, production operations), and the AI
   coding assistants/agents it explicitly names. The model must summarise only
   what is in the resume — never invent experience or credentials.
4. If the LLM call fails or returns an unusable reply, record an error and stop; do
   not substitute a deterministic description. Transient provider/network failures
   (`Connection error.`, 429/5xx) are retried a bounded number of times (default 2
   extra attempts with exponential backoff) before that error is recorded;
   parameter/validation failures are not retried.
5. Map the description to the resume file in the resume-description store, keyed by
   the resume's canonical path; update the entry when the same file is
   re-described so no duplicate entries pile up.
6. Never rename, move, or modify the resume file — only the sidecar store changes.
7. Refresh the stored description when the resume file changed (its mtime or size
   differs from what was recorded) **or** when the stored entry's
   `profile_version` is older than the current profile schema. A prompt/schema
   improvement must reach the matcher; bumping `PROFILE_VERSION` re-describes the
   pool once on the next run.
8. When matching for a job (Task 3), pass the job description and every resume's
   stored LLM description to the **LLM** and ask it to **rate every candidate**
   (`strong`/`partial`/`none`, best first) and then choose the strongest one, or
   **none**. If the single `choice` is not strong but another candidate is rated
   `strong`, select that strong candidate rather than skipping the job. Do **not**
   call `score_resume` or any other deterministic scorer.
9. Validate the chosen id against the candidate list, record the chosen resume's
   path, the per-candidate ratings, and the LLM's rationale (including any
   strong-rating override), and hand that resume to Task 4 to attach/upload.

**Acceptance criteria**
- A newly added resume gets a short description produced by the LLM, stored and
  mapped to its file.
- The description is validated/normalised and the LLM summarises only what is in
  the resume (it does not invent skills, titles, or years).
- On later jobs the stored description is reused when its file signature and
  `profile_version` are current, so the resume is not re-extracted or re-summarised
  to rebuild the description; an older profile version is re-described once.
- The **LLM** rates every candidate and picks the strongest resume directly from
  the job description and the resume descriptions; the deterministic weighted
  scorer (`score_resume`) is **not** used anywhere in the match.
- Every resume considered for a job has an LLM description; a resume without one is
  an error, not matched from its raw text.
- Re-describing the same file updates its entry instead of creating a duplicate.
- If the LLM is not configured, or the call fails or returns an unusable reply, an
  error is recorded and the run stops cleanly — no deterministic fallback is used.
  Transient provider/network failures are retried a bounded number of times first.
- Resume files are never modified, renamed, or moved.
- A candidate the LLM rates `strong` is selected even when the model's single
  `choice` was `partial`/`none`; the job is not skipped while a strong candidate
  exists.
- The chosen resume's path, the per-candidate ratings, and the matching rationale
  are recorded, and the selected resume is the one Task 4 attaches/uploads.

**Notes**
- The short description is generated by the **LLM** (same configured model as
  Task 4.1, temperature 0) from the raw resume text. There is **no deterministic
  fallback**: if the LLM is unconfigured, errors, or returns an unusable reply, the
  subtask records an error and stops rather than describing or matching another way.
- The match itself is an **LLM decision** over the stored descriptions — the
  deterministic keyword/weight scorer is removed from the matching path.
- A resume with no stored description is an error rather than being matched from
  its raw text.
- The LLM only summarises the resume it is given — it must not add skills, titles,
  or years that are not present in the file.
- The store maps resume path → description (plus the file's mtime/size and the
  `profile_version`) and never contains credentials.
- Uploading/attaching the resume is still Task 4's job; this subtask only chooses
  the resume.
- **Sync note (BUG-078/BUG-079):** the profile also carries factual highlights and
  named AI coding tools, and the match reply rates every candidate. The cache is
  versioned (`PROFILE_VERSION`) so profiles written by an older prompt/schema are
  re-described instead of reused.
- **Sync note (BUG-080):** transient `Connection error.`/429/5xx responses are
  retried a bounded number of times before a Task 3.2 error is recorded; a
  deterministic failure (bad request/API key) and an unusable reply are not
  retried by this transport retry.
- Depends on Subtask 3.1: when the human uploads a resume, 3.1 hands it here to be
  LLM-described **before** it is used. Subtask 3.1 then uses that resume directly
  for the current job (no re-match); the stored description is what later jobs
  match against.

## Main flow — Read the job description and pick the best-matching resume (LLM)

**Status:** ✅ Done

**Goal:** The end-to-end path that ties the pieces together: read the open job's
description, let the LLM rate every candidate and choose the strongest resume
using the stored descriptions from Subtask 3.2, and hand the chosen resume to
Task 4. This is the last piece to build, after 3.1 and 3.2 are in place and tested.

**Steps**
1. Read the job description from the open job (title, company, location, and the
   full description body).
2. List the files in `resumes/`.
3. If the folder is empty, there is nothing for the LLM to choose: treat the job
   as a **no match** and, in legacy mode, hand off to Subtask 3.1, which reuses a
   remembered resume or asks the human (an empty pool is a no-match, not an
   error). In Task 16 strict mode this is a clean skip.
4. Build the candidate list from the resumes and their stored LLM descriptions
   (Subtask 3.2). A resume with no stored description is an error, not matched
   from its raw text.
5. Ask the LLM to **rate every candidate** (best first) and **choose the strongest**
   resume, or to answer **none** when nothing fits. It returns the per-candidate
   ratings, the chosen candidate id, its fit, and a short rationale. If the single
   choice is `partial` but another candidate is rated `strong`, use the strong
   candidate.
6. Validate the choice: it must reference a real candidate in the list; ratings
   that reference an unknown id are ignored.
7. Record the selected file path, the per-candidate ratings, and the LLM's
   rationale (including a note when a strong rating overrode the single choice).
8. If **no candidate is rated `strong`** — the LLM answers **none**, returns only
   `partial`/`none` ratings, or returns an invalid choice with no strong rating —
   treat the job as a **no match** and hand off to Subtask 3.1 (reuse a remembered
   resume, or ask the human). Do not guess. In Task 16 strict mode this becomes a
   clean skip instead.

**Acceptance criteria**
- The job description is read successfully.
- Every resume in `resumes/` is considered by the LLM.
- The LLM is the only resume-matching path — there is **no** deterministic
  keyword/weight scoring fallback.
- Exactly one resume is selected as the best strong match (or no candidate is
  rated strong).
- A candidate the LLM rates `strong` is selected even when the model's single
  choice was `partial`; an all-partial/none reply is the only no-match case.
- The chosen resume path, the per-candidate ratings, and the LLM's matching
  rationale are recorded in the run state/log.
- A reply with no strong candidate (none, all partial/none, or an invalid choice
  with no strong rating) is a no-match: in legacy mode Subtask 3.1 handles it, in
  strict mode (Task 16) it is a clean skip — never a guessed or deterministic
  lowest-score pick.

**Notes**
- **No fallback:** the deterministic keyword/weight scorer is removed from the
  matching path. The LLM decision is the only path.
- The LLM may choose **only** among the provided candidates; it must never invent
  a file name or path. Ratings for unknown ids are ignored.
- The choice must be explainable: the LLM's rationale and per-candidate ratings
  are stored. A strong-rating override records which candidate was used and why.
- **Sync note (BUG-078):** the gate uses the LLM's own per-candidate ratings, so a
  single partial `choice` cannot discard a different candidate the LLM rated
  `strong`.
- Do not rename, move, or modify the resume files.
- The prompt and stored rationale must not contain credentials or other secrets.
- Subtask 3.2 supplies the per-resume descriptions the LLM matches against;
  Subtask 3.1 handles the "no match" fallback (remembered resume / ask human).
- The selected resume is the one Task 4 attaches/uploads; this task does **not**
  submit the application.
