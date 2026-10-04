# Agent Guidelines

- Do not commit or push code unless explicitly told to do so.
- Task tracking: tasks live in `task/task.md`. When a task is finished, mark it
  ✅ Done in `task.md` **and** add an entry to `task/doneTask.md` (number, title,
  completion date, what was done, and supporting evidence). Keep the log in
  `doneTask.md` up to date whenever a task is completed.

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

