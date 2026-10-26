# Task — Self-Healing Loop Engineering System for LinkedIn Easy Apply

**Status:** 🟡 In progress

**Goal:** Make the live Easy Apply run resilient to LinkedIn's dynamic form/element
changes. When a **new crash** is discovered (for example a step that cannot be
advanced, a control that disappears, or an unexpected runtime error), the loop
must:

1. **Record** the failure as a structured bug report (symptom, root-cause context,
   screenshots/DOM evidence).
2. **Close the current browser session** cleanly so no stale CDP/profile state
   survives.
3. **Fix the recorded issue immediately** in the code path that failed, respecting
   the repository's bug-log and test rules.
4. **Test the updated code** (unit tests and, where the failure was browser-level,
   a live-browser regression check).
5. **Reopen the browser** and **resume the same LinkedIn job application** from
   the failing step rather than starting over.

The loop is **bounded**: at most **two or three repair attempts** per failure
fingerprint. If the tests keep failing after that, preserve the evidence (bug
report, logs, screenshots) and **stop cleanly** instead of repeatedly patching
the code.

## Preconditions
- Tasks 1-10 are implemented and the live Easy Apply pipeline runs end to end.
- A failure report format exists (`known Bugs/bug_log.md` plus per-task bug
  files); the new failure is appended there with a stable ID.
- The agent must never click **Submit application** — human submission remains
  manual.

## Inputs
- The current Easy Apply form walk state (current step, already-filled fields,
  resume selection, known answers).
- The failure: exception/error message, DOM snapshot, page screenshot, console
  logs, and the task/node that failed.
- Existing bug-log schema (`known Bugs/*.md`).
- Repair-attempt limit (default **3**).

## Steps
1. **Detect the failure.** Any unhandled exception or a hard stop in the browser
   loop (e.g. `form did not advance`, missing resume control, unknown required
   field) triggers the self-healing path instead of just ending the run.
2. **Capture evidence.** Save a full-page screenshot, the failing element's DOM
   snippet, the current step title/number, the console error, and the attempted
   action. Write them to a new failure folder under `data/debug/` and to a new
   `BUG-NNN` entry in the appropriate `known Bugs/task_N_bugs.md` file (and
   `bug_log.md` index).
3. **Classify the failure.** Determine whether it is a *known* bug (already
   logged) or a *new* bug. Known bugs reuse their existing fix; new bugs get a
   new ID and are marked 🔴 Open until fixed.
4. **Close the browser session** cleanly (same path as `cleanup`, leaving no
   orphan CDP connection or profile lock).
5. **Fix the code.** Implement the smallest targeted fix for the failing step
   (new selector fallback, better wait, handling a new control type, etc.). Keep
   the fix consistent with the surrounding code and update interrelated callers.
6. **Add or update a regression test** for the failure (unit test when possible;
   live-browser test when the failure is DOM-dependent).
7. **Run the tests** (focused test file first, then the full suite). If tests
   fail, iterate up to the repair-attempt limit (**2-3 attempts**).
8. **Reopen the browser** and **re-run the LinkedIn job application** from the
   failing step. The previously filled fields and answers are preserved; the
   resume is re-attached if needed.
9. **Stop cleanly after the attempt limit.** If the failure is still present after
   the limit, keep all logs/screenshots/bug report, mark the bug 🔴 Open, and end
   the run without further patching.
10. **Record the outcome.** Update the bug-log entry with the fix commit hash,
    test evidence, and status (🟢 Fixed once tests pass; 🔴 Open if attempts
    exhausted).

## Acceptance criteria
- A new crash is recorded as a `BUG-NNN` entry with symptom, root cause, fix,
  status, and evidence **before** the fix is attempted.
- The browser session is closed cleanly before code is changed, and reopened
  after tests pass.
- The fix is tested (unit and/or live browser) before the application is resumed.
- The same LinkedIn job application resumes from the failing step after recovery.
- Repair attempts are capped (default 3); exceeding the cap preserves evidence
  and stops the run without repeated patching.
- The agent never clicks **Submit application**.
- The bug-log index (`known Bugs/bug_log.md`) stays in sync with every new entry.

## Notes
- **Why close the browser?** The old session may hold stale CDP state or a locked
  profile; closing it prevents the next run from inheriting the crash.
- **Resume, don't restart.** After recovery, pick up the Easy Apply walk at the
  step that failed rather than refilling already-completed steps.
- **Record first, fix second.** Evidence captured at crash time is the only
  reliable way to reproduce dynamic LinkedIn DOM changes.
- **Stop cleanly.** Repeated patching without success is worse than stopping; the
  preserved logs let a human diagnose the issue offline.
- Follow the repository's file-size limit: if a modified file crosses 415 lines,
  split it into a package folder with one module per concern and a thin
  `__init__.py`.

## Subtask — Failure detection & evidence capture
**Status:** 🟡 In progress

Detect any hard stop in the Easy Apply loop (unhandled exception, missing
control, un-advanceable step) and write a structured failure report (screenshot,
DOM snippet, step info, console error) to `data/debug/` and a `BUG-NNN` entry in
`known Bugs/`.

## Subtask — Clean session close & code repair
**Status:** 🟡 In progress

Close the current browser session cleanly, implement the smallest targeted fix
for the failing step, and add a regression test for it.

## Subtask — Bounded retry with resume
**Status:** 🟡 In progress

Reopen the browser and resume the same LinkedIn job application from the failing
step. Retry up to the repair-attempt limit (default 3); on exhaustion preserve
evidence and stop cleanly.

## Subtask — Bug-log integration
**Status:** 🟡 In progress

Every recorded failure becomes a `BUG-NNN` entry with symptom, root cause, fix,
status, and evidence; the `bug_log.md` index is updated in the same change.
