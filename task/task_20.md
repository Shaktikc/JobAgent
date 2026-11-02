# Task 20 — Correct invalid Easy Apply inputs; log and skip unresolved applications

**Status:** 🟡 In progress

**Goal:** When LinkedIn Easy Apply displays an invalid-input validation error,
try to fix the rejected fields by entering valid input and retrying the current
step. If correction does not work, save a JSON log containing the job link and
validation details, close that Easy Apply form, and continue to the next eligible
job. Do not get stuck retrying the same application.

**Reported example**
- Screenshot: `C:/Users/shakt/OneDrive/Pictures/Screenshots 1/Screenshot 2026-11-02 093728.png`.
- Job: https://www.linkedin.com/jobs/view/4485430037/ (nxzen).
- The screenshot shows multiple fields marked `Invalid input`, including an
  answer with a `15/20` character counter. Other answers show `555/20` and
  `485/20`, so not every visible rejection can be attributed to a website bug.
  First try a valid correction that respects the field's actual constraints.
  If LinkedIn still rejects the input, log and skip without needing to prove
  whether LinkedIn or the entered answer caused the rejection.

**Preconditions**
- The agent can open and fill Easy Apply and move to the next eligible job.
- Submission remains a manual human action.

**Inputs**
- Current job URL, job ID, title, and company when available.
- The current Easy Apply step's visible validation errors, field labels,
  current controls, allowed options, and input constraints.
- Existing applicant answers, selected resume, and other approved information
  from which a truthful valid answer can be derived.
- Existing run state, skip tracking, logging, and next-job navigation.

**Steps**
1. Inspect the current Easy Apply step dynamically after filling controls and
   attempting normal navigation. Detect visible `Invalid input` messages and
   equivalent field-validation errors that block progress; do not treat
   unrelated page text or hidden messages as a failure.
2. Discover the rejected controls and their constraints at runtime, including
   required status, expected type/format, character limits, numeric ranges, and
   allowed options. Use visible feedback and control metadata to correct the
   input: for example, enter a known numeric answer in the required format or
   rewrite a free-text answer within the character limit while preserving its
   facts. Respect Task 21's required-question policy. Do not invent applicant
   information, change factual numbers merely to pass validation, or blindly
   truncate an answer into a different meaning.
3. Make at most one correction pass per blocked step, then retry its normal
   Next/Review navigation once and inspect the resulting validation feedback.
   Re-discover controls after re-renders rather than assuming fixed steps or
   positions. If a known-valid value was rejected, re-enter it once before this
   retry. Never click Submit application as part of correction or retry.
4. If validation clears and the step advances or reaches review, continue the
   existing application flow. Do not log or count a successfully corrected job
   as skipped. If validation still blocks progress, or no truthful valid
   correction is available, stop retrying and follow the logging/skip steps
   below. Do not repeatedly click Next, wait for the human to repair the field,
   or invoke structural self-healing for this validation outcome.
5. Capture the current job's direct link before closing the form or navigating
   away. Prefer a canonical `https://www.linkedin.com/jobs/view/<job-id>/`
   link when the ID is available; never log only the search-results URL.
6. Add a durable skip record to `data/invalid_input_skips.json`, stored as a
   valid JSON array of records. Include timestamp, job URL, job ID/title/company
   when available, reason `invalid_input`, visible error text, affected field
   labels when available, whether correction was attempted, retry count, and
   why correction failed or could not be attempted. Preserve earlier records
   across jobs and runs; update the file atomically so interrupted writes do
   not corrupt existing entries. Avoid storing the applicant's answer values
   or other unnecessary personal data, including values echoed in error text.
7. Persist the record before leaving the job. If writing the log fails, report
   the failure clearly and stop safely instead of silently losing the link.
8. Close the Easy Apply modal and handle any close/discard confirmation needed
   to leave it. Record the job as skipped for this run, never as applied or
   submitted. Preserve the logged link for later manual review.
   Confirm the modal is closed before selecting another job; if cleanup fails,
   report the failure and stop safely with the saved link preserved.
9. Continue the existing next-job loop automatically, respecting existing
   eligibility rules and pagination/date-range fallback. Do not reopen the
   same rejected job during the run or stop to wait for manual submission.
10. Show a concise progress message with the correction result or, when skipped,
    the skip reason and saved job link.
    Jobs whose forms have no validation errors keep their existing flow.
11. Never click **Submit application**. Entering valid input and retrying a
    step does not authorize final submission; submission remains manual.

**Acceptance criteria**
- A visible invalid-input error on any dynamically discovered Easy Apply step
  triggers a bounded attempt to enter truthful valid input and retry the step.
  Coverage includes formatting errors and answers exceeding character limits.
- A successful correction resumes the same application normally without a skip
  record, skip count, or automatic submission.
- If validation persists after the single correction/retry pass, including an
  apparently valid answer rejected by LinkedIn, the job is logged and skipped.
  If no reliable correction exists, log that reason and skip without inventing
  an answer or waiting indefinitely for human intervention.
- Each skipped application has a durable, usable direct job link, validation
  reason, and correction outcome in a parseable `.json` file; earlier records
  survive later jobs, runs, and interrupted writes.
- The modal closes safely and the next eligible job opens automatically.
- A skipped job is not marked applied and is not retried in the same run.
- Hidden error text and unrelated text do not cause a skip; forms without
  validation errors continue normally.
- A log-write failure is visible and does not silently discard the job link.
- Relevant automated tests cover detection, constraint-aware correction,
  successful recovery, persistent rejection, unavailable valid answers, the
  retry limit, JSON logging/preservation, write failure, modal cleanup, skip
  accounting, and continuation without retry loops.
- Live-browser verification on LinkedIn confirms both paths: a corrected input
  allows the same application to continue, and an unresolved validation error
  saves a JSON record with the direct job link, closes the form, and opens the
  next eligible job. Neither path submits an application. Unit tests alone do
  not complete this task.

**Implementation notes**
- This update revises the task requirements only; implementation and verification
  of the correction-first behavior are pending.
- Put the new validation-correction/skip/logging behavior in new modules and
  respect the 415-line source-file limit.
- Review interrelated form filling/navigation, outcome/state models, next-job
  loop, Task 21 required-question filtering, UI progress, self-healing routing,
  tests and monkeypatch targets, and documentation when implementing this task.
- Log any bugs fixed during implementation under `known Bugs/task_20_bugs.md`
  and update `known Bugs/bug_log.md`, with evidence and accurate status.
- Keep Task 20 🟡 In progress in this file and the index. Mark it ✅ Done only
  after implementation, live-browser verification, and the user's explicit
  confirmation that the task works.
