# Task 25 — On invalid input, convert the answer's type (number ↔ text) before giving up

**Status:** 🟡 In progress

**Goal:** When an Easy Apply field is rejected with an invalid-input error and the
answer is otherwise truthful and correct, first try to fix the answer's *type* —
convert the same answer between a number and its text form (and vice versa) —
before falling back to any other correction or to Task 20's log-and-skip path.

**Reported example**

- Question: "How many years of experience?"
- Answer given: `2 years`
- Rejected with: `Invalid input` (the field expects a plain number).
- Expected behaviour: recognise the same fact, enter it as `2`, retry the step,
  and only if that is still rejected use the existing correction/skip logic.

**Preconditions**

- Task 20 (invalid-input correction, logging, and skipping) already detects a
  visible invalid-input error on a discovered Easy Apply step and can re-enter a
  corrected value and retry the step.
- The rejected field, its expected type/format, its constraints, and the
  currently entered answer are all discoverable at runtime (already collected by
  Task 20's validation discovery).
- Submission remains a manual human action.

**Inputs**

- The rejected field's discovered metadata: label/question, control kind,
  `type`, `inputmode`, `pattern`, min/max/step, character limits, and the
  visible validation message.
- The current answer the agent entered for that field (its literal string).
- Approved applicant information only (Task 5/10/12 answers and the selected
  resume/job description) — the conversion must not invent facts.

**Steps**

1. Extend the validation correction flow with a **type-conversion pass** that
   runs when an invalid-input error is detected and before any other correction
   (and before Task 20's log-and-skip path).
2. Detect the type mismatch for a rejected field at runtime:
   - the field is numeric (`type="number"`, or `inputmode="numeric"/"decimal"`,
     or a numeric `pattern`/range) but the answer contains non-numeric text, or
   - the field is a free-text control but the answer is a bare number that the
     field rejects (for example a text field expecting "2 years" style wording).
3. Convert the answer **in the truthful direction only**:
   - **text → number:** extract the single numeric fact from the answer when it
     is unambiguous — e.g. `2 years` → `2`, `5+` → `5`, `~3` → `3`. Convert only
     when the number is the answer's whole meaning (a count, years, etc.). If the
     answer holds several numbers, a range, a unit that implies a different
     scale, or no number at all, do **not** convert; leave it to the existing
     correction/skip logic.
   - **number → text:** when a text field rejects a bare number, restate the same
     value with its unit/context when that wording is already known from the
     question (e.g. `2` → `2 years` for a years-of-experience question). Never
     add a unit or fact that is not implied by the question or approved answers.
4. Respect the field's discovered constraints on the converted value (min/max,
   step, character limit, `pattern`). A conversion that violates them is not
   entered.
5. Enter the converted value on the rejected control, then follow Task 20's
   existing retry discipline: at most one correction pass per blocked step, one
   normal Next/Review retry, re-discover controls after re-render, and never
   click **Submit application**.
6. If the converted value is accepted and the step advances, continue the
   existing application flow. Do not log or count this job as skipped.
7. If the conversion is not possible or the converted value is still rejected,
   fall through unchanged to Task 20's remaining correction options and its
   log-and-skip path (`data/invalid_input_skips.json`). Record in the skip
   record that a type conversion was attempted (and its outcome) alongside the
   existing correction fields.
8. Show a concise progress message when a conversion fixed the field (e.g.
   `Type conversion: "2 years" -> 2`).
9. Do not hardcode any question text, field name, step position, or control
   type; everything must be discovered at runtime.

**Acceptance criteria**

- A numeric field rejecting `2 years` (or any answer whose whole meaning is one
  unambiguous number) is retried with `2` in the same application, and the
  application continues without a skip record when it is accepted.
- A text field rejecting a bare number re-enters the same value as wording that
  is already implied by the question, without inventing a unit or fact.
- Conversion never changes the answer's meaning: no rounding, unit conversion,
  range picking, or multi-number guess. An ambiguous answer is not converted.
- Conversion respects the field's discovered constraints and is not entered when
  it would violate them.
- Conversion happens before the log-and-skip path; an unconvertible or still
  rejected answer falls through to the existing Task 20 behaviour unchanged,
  with the skip record noting the conversion attempt.
- No submission is triggered; submission stays manual.
- Relevant automated tests cover text→number, number→text, ambiguous answers,
  constraint violations, still-rejected converted values, skip-record fields,
  and fall-through to the existing correction/skip flow.
- Live-browser verification on LinkedIn confirms the reported example works
  end-to-end: `2 years` on a numeric years-of-experience field is converted to
  `2`, accepted, and the same application continues. Unit tests alone do not
  complete this task.

**Implementation notes**

- This task only creates the requirement; implementation is pending and must
  not start until it is picked up.
- Put the type-conversion behaviour in new modules and respect the 415-line
  source-file limit. Expect to extend the `linkedin_validation` package
  (conversion helper plus wiring in correction/navigation) rather than growing
  any single file past the limit.
- Review interrelated code when implementing: Task 20's correction, navigation
  retry, constraint helpers, skip/journal records and their schema, Task 21
  required-question filtering, Task 10/12 answer formatting, UI progress
  messages, tests and monkeypatch targets, and documentation.
- Log any bugs fixed during implementation under `known Bugs/task_25_bugs.md`
  and update `known Bugs/bug_log.md`, with evidence and accurate status. Create
  the file without waiting for approval.
- Keep Task 25 🟡 In progress in this file and the index while it is being
  worked on. Mark it ✅ Done only after implementation, live-browser
  verification, and the user's explicit confirmation that the task works.
