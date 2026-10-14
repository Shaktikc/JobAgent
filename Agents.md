# Agent Guidelines

- Do not commit or push code unless explicitly told to do so.
- Do not edit anything in the task files (the `task/` folder: the `task/task.md`
  index and each `task/task_N.md`) unless the user has reviewed the change and
  given explicit approval.
- Task tracking: each task lives in its own file, `task/task_N.md`, listed in the
  `task/task.md` index. Once the user has reviewed and approved the completed
  work, mark the task ✅ Done in its `task/task_N.md` file and update the status
  shown in `task/task.md`.
- Whenever you change code for any task (for example a bug fix), also update
  any interrelated code that the change could affect, including code used by
  other tasks. Do not leave other parts of the codebase inconsistent.
- Always verify that changed code works by testing it (run the relevant tests,
  build, or a manual check) before declaring the task complete.
- **Bug log (important — never skip):** whenever you find and fix a bug, always
  record it in the bug log under `known Bugs/`. A fix with no log entry is **not
  complete**. See [Bug log](#bug-log-required) below.
- When implementing a new feature, create an entirely new file for it rather
  than adding it to an existing file. Before creating the file, ask the human
  for feedback on the file name and wait for their approval.

  
## Live browser verification (required)

- Always do the testing in a live browser to verify that the task actually works.
  Do not declare a task complete based only on reading the code or on unit tests.
- If it does not work, do not give up and do not declare the task done. Try to
  understand *why* it does not work (collect the real error, inspect the DOM,
  console, and network traffic), then change the code accordingly and test again.
- Repeat this loop — test in the browser, diagnose the cause, fix the code, and
  re-test — until the given task genuinely works.
- After changing automation code, actually run it against the real site and
  confirm the expected behavior. Never mark a task done on an untested assumption.

## Bug log (required)

This is a required step, not optional bookkeeping. **Whenever a bug is found
and fixed, log it and keep its status current — always.** Never fix a bug
silently.

- **Where:** bugs live under `known Bugs/`. Put each bug in the file for its
  task (`task_1_bugs.md` … `task_6_bugs.md`) or, when no single task owns the
  root cause, in `general_bugs.md`. `known Bugs/bug_log.md` is the master index.
- **Every entry must record** the `Symptom` (what was observed), `Root cause`,
  `Fix`, `Status`, and `Evidence` (source files, tests, and the commit hash).
- **Always keep the status up to date**, using the shared markers:
  - 🟢 **Fixed** — fixed and guarded by evidence.
  - 🟡 **Fixed (superseded)** — fixed once, then replaced by a later change.
  - 🔴 **Open** — known, not fixed yet.
  - ⚪ **Won't fix** — intentionally not fixed.
- **Never delete or lose a logged bug.** If a later change replaces an earlier
  fix, change its status to 🟡 _Fixed (superseded)_ and say what replaced it —
  do not remove the entry.
- **Keep the index in sync:** add or update the matching row in
  `known Bugs/bug_log.md` in the same change as the fix.
- **A bug fix is only complete when** the code is fixed, the relevant test or
  live-browser check passes, and the bug log entry plus its status are updated.
- Ask the human for feedback on a new bug file's name before creating it (same
  rule as any new file).


## Browser automation

- **Treat the Easy Apply form as dynamic.** LinkedIn renders different steps,
  field layouts, and controls from job to job; the number and order of steps are
  not fixed. Never assume which step holds a control, or that a control appears
  at a fixed position.
- **Discover everything at runtime:** enumerate the current step's fields, find
  the resume control wherever it is (a radio list, a `<select>`, a file input, or
  an "Upload resume" button that reveals one), and find the navigation buttons on
  the current step.
- **Walk the form step by step** until the terminal step. If a step does not
  advance (for example a required answer is unknown and blocks Next), stop
  gracefully with a clear note instead of retrying blindly.
- **Never click Submit application** — submission is always a manual human step.

