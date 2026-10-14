# Task 8 — After the human submits a job, open the next one and repeat

**Status:** ✅ Done

**Goal:** The agent fills an application to its **last step** (only **Submit
application** remains) and the human reviews and submits (or applies to) that
job. Once that submission is detected, the agent **returns to the results list,
opens the next unapplied job, and repeats the whole process** — open Easy Apply,
read the description, choose a resume, fill the form, and wait for the human to
submit again — until a stopping condition is reached. The agent **never** clicks
**Submit application**; it only detects the human's submission.

**Preconditions**
- Task 6 is complete: cards already marked **"Applied"** are skipped.
- Task 7 is complete: when a whole results page is Applied the list is paginated
  to the next page (so the next unapplied job can be found).
- Tasks 2-4 work for a single job: open Easy Apply, read the description, match a
  resume, and fill the form to the terminal step.
- The human is available to review and submit each application (submission stays
  manual).
- This is a real run (`--no-dry-run`); a dry run does not loop and launches no
  browser.

**Inputs**
- The results list left open after a submission (the Easy Apply modal closes and
  the card becomes **"Applied"**).
- The per-job record of the job just submitted (title, company, chosen resume).
- `AUTOJOB_SESSION_MAX_JOBS` (default `5`; `0` = keep going until no unapplied job
  remains) — the safety cap on how many jobs one run may submit.
- `AUTOJOB_SESSION_KEEP_OPEN_TIMEOUT_SECONDS` (existing, default `1800`) — how long
  to wait for the human to submit **each** job before giving up.
- The live browser session opened for Tasks 1-4 (`browser_run_id`), reused across
  every iteration.

**Steps**
1. After Task 4 fills a job to its terminal step (only **Submit application**
   remains), leave the browser open and **wait for the human to submit** — do not
   click **Submit application**.
2. Poll the page (bounded by `AUTOJOB_SESSION_KEEP_OPEN_TIMEOUT_SECONDS`) for the
   submission signal: the Easy Apply modal closes and/or a post-submit
   confirmation ("Application sent", "Done") appears, and/or the job's card flips
   to **"Applied"**.
3. If the human closes the browser window without submitting, or the wait times
   out, **stop the loop gracefully** and finish the run, recording why.
4. If a submission is detected, record the job (title, company, chosen resume,
   index) on the Task 8 outcome and increment `jobs_applied`.
5. Return to the results list. **Re-read the job cards** on the current page; do
   not carry over the previous decision.
6. Run Task 6's skip-applied logic and, when the whole page is Applied, Task 7's
   pagination until the **first unapplied Easy Apply job** is found or there are no
   more pages.
7. If an unapplied job is found, open its Easy Apply form and repeat the process
   for it: read the description (Task 3), choose the best-matching resume
   (Task 3.2), fill the form (Tasks 4-5), then go back to step 1 (wait for the
   human to submit).
8. Stop the loop when any of the following holds:
   - `AUTOJOB_SESSION_MAX_JOBS` jobs have been submitted this run,
   - every job on every results page is **Applied** (nothing left to apply to),
   - the human closes the browser, or the per-job wait times out,
   - a step fails (no Easy Apply button, no resume selected, form not found) —
     stop gracefully with a clear note rather than retrying blindly,
   - the pagination controls or results list can no longer be found.
9. Keep the browser session open across iterations; close it **once**, in
   `cleanup`, when the loop ends (never while the human is reviewing).

**Acceptance criteria**
- After the human submits a job, the agent returns to the results list and opens
  the next unapplied job automatically.
- The agent repeats the full process (open Easy Apply → read description → match
  resume → fill → wait for submit) for each subsequent job.
- The agent **never** clicks **Submit application**; it only detects the human's
  submission.
- Cards already marked **"Applied"** are skipped, and pagination (Task 7) is used
  when a whole page is Applied.
- The loop stops at the jobs-per-run cap, when no unapplied job remains, when the
  human closes the browser, or on a failure — each with a clear note.
- The number of jobs submitted this run, and each job's title/company/resume, are
  recorded on the Task 8 outcome and surfaced in the log/CLI summary.
- The browser session is reused across iterations and closed exactly once at the
  end.
- A dry run does not loop and does not launch the browser.

**Notes**
- **Submission stays a manual human step:** the agent must **never** click
  **Submit application**. It waits for the human's click and detects the resulting
  page state.
- **Detect submission dynamically:** the confirmation markup varies job to job, so
  discover it at runtime — the modal closing, a "Done"/"Application sent"
  confirmation, and/or the card flipping to **"Applied"**. A modal dismissed (X)
  or the window closed **without** a submission confirmation is **not** a
  submission.
- **One session for the whole run:** iterations reuse the session Tasks 1-4 opened
  (`browser_run_id`); do not launch a new browser per job.
- **Re-read after every submission:** once the modal closes, re-read the cards and
  re-check their statuses (Task 6) instead of reusing the previous decision; the
  just-submitted card now reads **"Applied"**.
- **Cap the loop:** `AUTOJOB_SESSION_MAX_JOBS` bounds the run so a card that never
  updates can never loop forever, consistent with the existing click/page caps.
- **Record per job:** add a `Task8Outcome` (a list of per-job records plus
  `jobs_applied` and a `stopped_reason`) and expose it in the CLI summary.
- **Do not confuse the human's submit with an agent violation:** keep
  `Task4Outcome.submitted` meaning "the agent clicked Submit" (it must stay
  `False`); record the human's submission on `Task8Outcome`. Update `verify` so a
  run where the human submitted passes Task 8's criteria without treating the
  human's submission as a failure.
- **Graph gains a loop:** after the human-submit wait, route back to the
  job-selection step when a submission was detected and the cap is not reached;
  otherwise route to `cleanup`.
- Never close the browser while the human is reviewing; only close it when the
  loop ends.
- If a step cannot be found after a submission (results list, pagination, Easy
  Apply button), stop gracefully with a clear note instead of retrying blindly.

## Subtask 8.1 — Wait for and detect the human's submission (per job)

**Status:** ✅ Done

**Goal:** Replace the current "wait for the human to close the window" behaviour
with "wait for the human to **submit** the application, then hand control back to
the loop". The agent never clicks Submit.

**Preconditions**
- Task 4 has filled a job to the terminal step (`reached_terminal_step` is set).
- The live browser session is still open (`browser_run_id`).

**Inputs**
- The open Easy Apply modal on the terminal step.
- `AUTOJOB_SESSION_KEEP_OPEN_TIMEOUT_SECONDS` and
  `AUTOJOB_SESSION_KEEP_OPEN_POLL_SECONDS` (existing).

**Steps**
1. With the modal open on the terminal step, poll the page until one of:
   - a **submission signal** is seen (modal closes / "Application sent" / "Done"
     confirmation / the card flips to **"Applied"**), or
   - the human closes the browser window (CDP drops), or
   - the timeout elapses.
2. On a submission signal, mark the job as **submitted by the human** on the
   Task 8 outcome (never set `Task4Outcome.submitted`) and return `"submitted"`.
3. On the window closing, return `"closed"` (the loop ends gracefully).
4. On timeout, return `"timeout"` and close the session for the human.
5. Never click **Submit application** (or any control that submits).

**Acceptance criteria**
- A human submit is detected and reported as `"submitted"` without the agent
  clicking Submit.
- Closing the window without submitting reports `"closed"` and ends the loop.
- A timeout reports `"timeout"` and closes the session.
- `Task4Outcome.submitted` remains `False` throughout.

**Notes**
- Reuse the existing keep-open timeout/poll settings; the wait is per job.
- Prefer a focused, unit-testable helper (e.g. `await_human_submit(...)`) so the
  detection rule is testable without a real browser.

## Subtask 8.2 — Loop: open the next unapplied job and repeat

**Status:** ✅ Done

**Goal:** After a detected submission, return to the results list, find the next
unapplied job (Tasks 6-7), and run the full process again in the same session
until a stopping condition is reached.

**Preconditions**
- Subtask 8.1 returned `"submitted"`.
- The browser session is still open.

**Inputs**
- The results list (and its pagination controls) after the modal closed.
- `AUTOJOB_SESSION_MAX_JOBS` (cap).
- The per-job outcomes produced for each iteration.

**Steps**
1. Re-read the job cards on the current results page.
2. Skip the cards marked **"Applied"** (Task 6); when the whole page is Applied,
   paginate to the next page (Task 7) and re-read.
3. If no unapplied job exists on any page, stop with
   `stopped_reason="no unapplied jobs"`.
4. Open the first unapplied Easy Apply job and repeat Tasks 2-4: read the
   description, choose the resume, fill the form to the terminal step.
5. Wait for the human to submit again (Subtask 8.1).
6. Stop when `AUTOJOB_SESSION_MAX_JOBS` jobs have been submitted, no unapplied job
   remains, the human stops, or a step fails.
7. Record every iteration on the Task 8 outcome and close the session once at the
   end.

**Acceptance criteria**
- The next unapplied job is opened automatically after each submission.
- The full per-job process repeats for every job.
- The loop stops at the cap / when nothing remains / when the human stops / on a
  failure, each with a clear `stopped_reason`.
- Each submitted job's title/company/resume is recorded.
- The session is reused across iterations and closed exactly once.

**Notes**
- Advancing to the next job must never be mistaken for submitting: the agent only
  observes and fills; the human submits.
- Re-read the cards after every submission; do not reuse the previous decision.
- If a step cannot be found, stop gracefully with a clear note instead of retrying
  blindly.
- Never click **Submit application**.
