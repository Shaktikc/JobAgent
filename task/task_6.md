# Task 6 — Skip jobs already marked "Applied" and open the next unapplied job

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
