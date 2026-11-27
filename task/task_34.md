# Task 34 — Dismiss diverting pop-ups and keep applying to the current job

**Status:** Not started


**Goal**

- When LinkedIn shows a pop-up that pulls the agent away from applying to the
  current job, dismiss it and continue the Easy Apply flow for **that same
  job**. Do not skip the job or stop the run because of the pop-up.
- Example (from the user's screenshot, 2026-11-27): after clicking Easy Apply,
  LinkedIn shows **"This job may not be the best fit — position yourself to
  stand out"** with a list of other suggested jobs and two buttons,
  **Continue applying** and **Explore more jobs**, plus a close (✕) button.
  The agent must not click **Explore more jobs** or any suggested job link.

**Behaviour**

- Detect these pop-ups at runtime (any modal/dialog that is not the Easy Apply
  form itself). Never hard-code one dialog's position or step; treat this
  as dynamic, the same as the Easy Apply form.
- Prefer a button that keeps the application going (for example
  **Continue applying**). If the pop-up has no such button, close it (✕ /
  Dismiss / Escape). Then, if the Easy Apply form is not open, click
  **Easy Apply** again for the same job and carry on filling the form.
- Never click a button or link that navigates away from the current job
  (for example **Explore more jobs**, a suggested job, or **update your
  profile**).
- Handle the pop-up whenever it appears: before the form opens, between steps,
  or after a step advances. If the same pop-up keeps coming back and the form
  still cannot be reached after a few attempts, stop gracefully for that job
  with a clear note and log it, instead of looping.
- Log each dismissed pop-up (its heading text and the button used) in the run
  log and the on-page status panel.
- Do not interfere with dialogs that are part of the existing flow and already
  handled elsewhere (the Easy Apply form, the discard/save confirmation, the
  submission confirmation, the safety reminder).

**Verification**

- Unit tests for detecting the diverting pop-up and choosing the safe button
  (continue over close, never "Explore more jobs").
- Live browser check on LinkedIn (default search query): when the pop-up
  appears, the agent dismisses it and the Easy Apply form opens and is filled
  for the same job.
