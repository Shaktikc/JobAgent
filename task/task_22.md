# Task 22 — Choose automatic or manual application submission at startup

**Status:** 🟡 In progress

**Goal:** Before the agent starts, ask whether it should submit completed Easy Apply
applications automatically or leave each application ready for the human to
review and submit. In automatic mode, the agent submits the application after
successfully completing the dynamic form walk. In manual mode, current behavior
is preserved.

**Preconditions**
- The agent has a startup prompt flow (Task 18 and Task 17).
- Tasks 4, 5, 12, 20, and 21 can fill and validate the current Easy Apply form.
- Task 8 manages the per-job apply loop.

**Inputs**
- An interactive startup choice: automatic submission or manual submission.
- Whether the run is interactive, plus any explicit CLI/config override defined
  during implementation.
- The current form's discovered controls and validation outcome.

**Steps**
1. Before launching the browser, ask the human whether the agent should submit
   applications automatically or leave them for manual submission. Make the
   default explicit; preserve manual submission as the default when no choice
   can be collected (non-interactive run, EOF, or interrupt).
2. Store the resolved choice in run state and include it in the run summary.
   Ensure it survives Task 8's next-job loop and self-healing browser recovery.
3. In manual mode, retain the existing flow: fill and validate the form, stop at
   the terminal step, leave the browser open, and wait for the human to submit.
4. In automatic mode, discover the current step's controls at runtime and walk
   the form until its actual terminal step. Do not assume a fixed number or
   order of steps or buttons.
5. Click the terminal **Submit application** action only after all required
   fields are valid, no unresolved required answer remains, and the form has
   reached its terminal submission step. Confirm submission from the resulting
   UI before recording the job as submitted or advancing to the next job.
6. If a required answer is unknown, validation fails, the terminal action is
   ambiguous, or submission cannot be confirmed, stop that application without
   retrying blindly. Report the reason and leave the human able to review and
   submit it manually.
7. Apply this behavior only to supported LinkedIn Easy Apply forms. Do not
   submit through external application sites or other flows unless separately
   specified.

**Acceptance criteria**
- At interactive startup, the human is asked to choose automatic or manual
  submission before the browser launches.
- The default is manual; non-interactive runs and prompt interruption never
  silently enable automatic submission.
- Manual mode never clicks **Submit application** and retains the existing
  review-and-human-submit workflow.
- Automatic mode submits a fully completed, validated Easy Apply application,
  verifies the site's confirmation, then allows Task 8 to proceed.
- Dynamic forms are inspected step by step; no fixed step count or control
  position is assumed.
- Unknown required answers, validation errors, uncertain submit controls, and
  missing confirmation stop safely with a clear outcome; the agent does not
  retry a submission blindly.
- The selection is carried through the run loop and self-healing recovery.
- Tests cover prompt/default behavior, both modes, terminal-step discovery,
  validation/unknown-answer stopping, confirmation, and loop continuation.
- A live-browser check verifies automatic submission on a controlled Easy Apply
  flow and verifies manual mode leaves the terminal step untouched.

**Notes**
- The startup choice authorizes submission for the run; it does not bypass
  required-answer, validation, or confirmation checks.
- Preserve manual mode as the default for backward compatibility.
- Do not mark this task ✅ Done until the user verifies the implementation.
