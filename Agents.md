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
- When implementing a new feature, create an entirely new file for it rather
  than adding it to an existing file. Before creating the file, ask the human
  for feedback on the file name and wait for their approval.

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

