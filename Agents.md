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
- **Self-healing loop (important — never skip):** when a live Easy Apply run
  hits a **new** crash (a changed element, a missing control, a step that will
  not advance, or an unexpected exception), do not merely stop: record the
  failure, close the browser session cleanly, fix the root cause, test the fix,
  reopen the browser, and resume the **same** LinkedIn job application from the
  failing step. Cap repair attempts (default **3**) and stop with the evidence
  preserved if the tests keep failing. See
  [Self-healing loop](#self-healing-loop-required) below.
- **Bug log (important — never skip):** whenever you find and fix a bug, always
  record it in the bug log under `known Bugs/`. A fix with no log entry is **not
  complete**. See [Bug log](#bug-log-required) below.
- **Important update — no approval needed for file names, bug logs, or code
  splitting:** do **not** wait for human approval before choosing a file/folder
  name, creating a new file (including a new bug log file under `known Bugs/`),
  or splitting a file into a package folder. Pick a clear, descriptive name that
  follows the existing structure, create the file, and proceed.
- When implementing a new feature, create an entirely new file for it rather
  than adding it to an existing file. Choose a clear, descriptive file name
  yourself — no approval is required.
- **File-size limit (important — never skip):** when any code file you write or
  edit crosses **415 lines**, split it into a package folder with one module per
  concern — do not let a file keep growing past the limit. This applies to all
  **future** code, and also to any existing file you are currently working on
  that is already over the limit. Existing files you are **not** working on are
  left as-is unless the human explicitly asks to split them. See
  [File-size limit](#file-size-limit-required) below.

  
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

## Self-healing loop (required)

LinkedIn's Easy Apply form is dynamic, so a live run can encounter a **new**
layout, control, or step that the code has never seen. When that happens, follow
this loop instead of ending the run at the first failure:

1. **Record first.** Capture the failure before changing code: the error/traceback,
   the current job and Easy Apply step, a screenshot, the failing DOM snippet, and
   any console output. Add a `BUG-NNN` entry to the matching
   `known Bugs/task_N_bugs.md` (or `general_bugs.md`) and the `bug_log.md` index.
2. **Close the current browser session cleanly.** Do not leave a stale CDP
   connection or profile lock behind; the old session may be why the next attempt
   inherits the crash.
3. **Fix the root cause.** Implement the smallest targeted fix for the new element
   or step, following the existing code patterns and the file-size limit. Update
   every interrelated caller.
4. **Add a regression test** for the failure (unit test where possible, live
   browser test when the behavior depends on real DOM).
5. **Test the fix.** Run the focused test first, then the relevant suite (and the
   live-browser check required by this file). Do not reopen the browser on a fix
   that has not passed.
6. **Reopen the browser and resume the same job application** from the step that
   failed. Keep the answers already collected and re-attach the resume if needed.
   Do not start over at a different job unless the same job is genuinely gone.
7. **Cap the repair loop.** Allow at most **2-3 repair attempts** for the same
   failure fingerprint. If the tests still fail, preserve all logs, screenshots,
   and the bug entry (status 🔴 Open), stop the run, and report what remains —
   never keep patching or retrying indefinitely.

Never click **Submit application** during this loop; submission remains a manual
human step.

## Bug log (required)

This is a required step, not optional bookkeeping. **Whenever a bug is found
and fixed, log it and keep its status current — always.** Never fix a bug
silently.

- **Where:** bugs live under `known Bugs/`. Put each bug in the file for its
  task (`task_1_bugs.md` … `task_6_bugs.md`) or, when no single task owns the
  root cause, in `general_bugs.md`. `known Bugs/bug_log.md` is the master index.
- **No approval needed to create a bug log file.** If a matching bug file does
  not exist yet, create it (and its index row) yourself with a clear, descriptive
  name and log the bug — do not wait for the human.
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


## File-size limit (required)

A source file you write or modify must not stay above **415 lines**. When a file
crosses that limit, split it the same way Task 4's `linkedin_easy_apply_fill` was
split — a package folder with a thin `__init__.py` plus one module per concern:

- Create a folder (a package) named after the file (for example
  `src/tools/linkedin_easy_apply_fill/`) and move the code into it grouped by
  concern (queries/readers, core logic, resume/attachment, orchestration, …).
- Keep a thin `__init__.py` that re-exports the file's public API, so existing
  `from ... import ...` callers and lazy re-exports keep working unchanged.
- Update every interrelated piece: callers, lazy re-exports, tests (including
  `monkeypatch` targets, which must point at the module that actually calls the
  function), and docs.
- Split large literals (JS/SQL strings, etc.) by line range so they are copied
  byte-for-byte rather than retyped.
- Run the tests and lint to prove nothing broke.
- **Scope:** this applies to all **future** code — every new file you create and
  any file you edit that would end up over the limit. It also applies to any
  existing file that is **already over the limit and that you are currently
  working on**: split it as part of that work. Existing files you are **not**
  working on are left as-is unless the human explicitly asks you to split them.
- Create the package folder and its file names yourself with clear, descriptive
  names — no approval is required (same rule as any new file).


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

