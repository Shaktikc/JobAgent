# Task 20 — Skip applications with invalid-input errors and log their job links

**Status:** 🟡 In progress

**Goal:** When LinkedIn Easy Apply displays an invalid-input validation error,
skip that application, persist its job link and the error, and continue to the
next eligible job. This includes cases where the supplied answer appears valid
but LinkedIn still rejects it. Do not get stuck retrying the same application.

**Reported example**
- Screenshot: `C:/Users/shakt/OneDrive/Pictures/Screenshots 1/Screenshot 2026-11-02 093728.png`.
- Job: https://www.linkedin.com/jobs/view/4485430037/ (nxzen).
- The screenshot shows multiple fields marked `Invalid input`, including an
  answer with a `15/20` character counter. Other answers show `555/20` and
  `485/20`, so not every visible rejection can be attributed to a website bug.
  The skip policy applies without needing to prove whether LinkedIn or the
  entered answer caused the rejection.

**Preconditions**
- The agent can open and fill Easy Apply and move to the next eligible job.
- Submission remains a manual human action.

**Inputs**
- Current job URL, job ID, title, and company when available.
- The current Easy Apply step's visible validation errors and field labels.
- Existing run state, skip tracking, logging, and next-job navigation.

**Steps**
1. Inspect the current Easy Apply step dynamically after filling controls and
   attempting normal navigation. Detect visible `Invalid input` messages and
   equivalent field-validation errors that block progress; do not treat
   unrelated page text or hidden messages as a failure.
2. When such an error occurs, stop processing that application. Do not keep
   changing answers, repeatedly clicking Next, asking the human to fix the
   rejected field, or invoking self-healing for this validation outcome.
3. Capture the current job's direct link before closing the form or navigating
   away. Prefer a canonical `https://www.linkedin.com/jobs/view/<job-id>/`
   link when the ID is available; never log only the search-results URL.
4. Append a durable skip record to a dedicated log, for example
   `data/invalid_input_skips.jsonl`. Include timestamp, job URL, job ID/title/
   company when available, reason `invalid_input`, visible error text, and
   affected field labels when available. Avoid storing the applicant's answer
   values or other unnecessary personal data.
5. Persist the record before leaving the job. If writing the log fails, report
   the failure clearly and stop safely instead of silently losing the link.
6. Close the Easy Apply modal and handle any close/discard confirmation needed
   to leave it. Record the job as skipped for this run, never as applied or
   submitted. Preserve the logged link for later manual review.
7. Continue the existing next-job loop automatically, respecting existing
   eligibility rules and pagination/date-range fallback. Do not reopen the
   same rejected job during the run or stop to wait for manual submission.
8. Show a concise progress message with the skip reason and saved job link.
   Jobs whose forms have no validation errors keep their existing flow.
9. Never click **Submit application**.

**Acceptance criteria**
- A visible invalid-input error on any dynamically discovered Easy Apply step
  causes the job to be logged and skipped, including an apparently valid answer
  rejected by LinkedIn and an answer exceeding a displayed character limit.
- Each skipped application has a durable, usable direct job link and the
  validation reason; earlier log records survive later runs.
- The modal closes safely and the next eligible job opens automatically.
- A skipped job is not marked applied and is not retried in the same run.
- Hidden error text and unrelated text do not cause a skip; forms without
  validation errors continue normally.
- A log-write failure is visible and does not silently discard the job link.
- Relevant automated tests cover detection, durable logging, write failure,
  modal cleanup, skip accounting, and continuation without retry loops.
- Live-browser verification on LinkedIn confirms the validation error is
  detected, the direct link is saved, and the next eligible job opens without
  submitting an application. Unit tests alone do not complete this task.

**Implementation notes**
- Creation only is authorized now; implementation and verification are pending.
- Put the new validation-skip/logging behavior in a new module and respect the
  415-line source-file limit.
- Review interrelated form filling/navigation, outcome/state models, next-job
  loop, UI progress, self-healing routing, tests and monkeypatch targets, and
  documentation when implementing this task.
- Log any bugs fixed during implementation under `known Bugs/task_20_bugs.md`
  and update `known Bugs/bug_log.md`, with evidence and accurate status.
- Mark Task 20 in progress only when implementation starts, and done in both
  this file and the index only after implementation and live verification.
