# Task 25 — On invalid input, convert the answer's type (number ↔ text) before giving up

**Status:** ✅ Done

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

## Subtask 25.1 — On invalid input, shorten an over-limit answer to the field's discovered maximum length

**Status:** ✅ Done

**Goal:** When a required Easy Apply text field rejects its answer with a
visible invalid-input / too-long error and the field has a discovered maximum
character length that the answer exceeds, shorten the same answer to fit that
maximum, re-enter it, and retry the step. This must happen before Task 20's
log-and-skip path so a correct answer that is merely too long does not cause
the application to be skipped.

**Reported example**

- A required text question shows `Invalid input` (or `Exceeds the maximum
  length`) while its visible counter reads `555/20` or `15/20`.
- The answer's content is acceptable, but it is longer than the field allows.
- Expected behaviour: recognise the `20`-character maximum, shorten the answer
  to 20 characters or fewer without inventing or changing leading facts,
  re-enter it, retry the step once, and continue the same application.
- Current behaviour: `_within_constraints` in
  `src/tools/linkedin_validation/constraints.py` vetoes the over-limit value and
  `corrected_value` deliberately refuses to clip text, so the existing flow
  falls through to the grounded chooser and then to Task 20's skip path.

**Preconditions**

- Task 20's validation discovery already reports the rejected field, its
  visible message, and its constraints. `detection.py` already reads a native
  `maxlength` and a visible `N / M` character counter; this subtask reuses
  that metadata and must not add a second, conflicting limit reader.
- Task 25's type-conversion pass and Task 20's fact-preserving correction remain
  in place. Length shortening is an additional repair, not a replacement for
  them.
- Only required questions are eligible (Task 21). Submission remains a manual
  human action.

**Inputs**

- The rejected field's discovered metadata: label/question, control kind,
  `type`, `maxlength`, `minlength`, `pattern`, current value, and the visible
  validation message.
- The literal answer the agent entered for that field (recovered with the same
  logic as `conversion_source`, including native input sanitisation).
- Approved applicant information only. Shortening may drop trailing wording but
  must never invent content, change a number, remove a negation, or add a unit.
- The visible character counter and any field-associated helper wording such as
  "Maximum 20 characters" / "up to 20 characters" / "20 character limit" when
  it can be tied to this control.

**Steps**

1. Add a **length-limit recovery pass** that runs when a visible
   invalid-input/too-long error is detected, before Task 20's skip path. Run it
   after the safe type-conversion pass, because a type conversion can itself
   shorten an over-limit value (e.g. `2 years` → `2`), and after the existing
   fact-preserving grounded alternative has been tried. If that alternative
   fits, use it; otherwise this pass is the last automatic repair before skip.
2. Discover the maximum length at runtime:
   - a native `maxlength` attribute on the rejected control, when present and
     greater than zero;
   - otherwise a visible character counter associated with the control
     (`N / M`), using the limit `M` already parsed by `detection.py`;
   - otherwise explicit field-related wording that states a maximum, only when
     it is visible, associated with this control, and unambiguous.
   Do not infer a limit from unrelated page numbers, dates, or other questions.
3. Compare the entered answer with the limit using the same UTF-16 code-unit
   length the browser uses (`len(value.encode("utf-16-le")) // 2`). Only act
   when the answer is longer than the limit.
4. Never shorten a numeric answer or a numeric control (`type="number"`,
   numeric `inputmode`, numeric bounds/pattern, or a bare number). Those belong
   to Subtask 25's type-conversion logic. Never truncate digits, signs, decimal
   points, or a single numeric fact.
5. Never shorten an answer that contains a negation (`no`, `not`, `never`,
   `without`, contractions such as `don't`/`can't`, etc.), because dropping a
   trailing negation can reverse the answer's meaning. Leave it to the existing
   correction/skip flow.
6. Shorten deterministically, preserving the leading facts and never inventing
   wording:
   1. first collapse repeated whitespace and trim; if that alone fits, use it;
   2. otherwise take the longest word-boundary prefix that fits, then trim
      trailing whitespace, punctuation, and dangling conjunctions/prepositions
      (`and`, `or`, `but`, `with`, `for`, `to`, `of`, `in`, `on`, `at`, `by`,
      `from`);
   3. only if no word boundary fits, use a character-boundary prefix, never
      splitting a surrogate pair or a URL/e-mail/identifier token;
   4. reject any candidate whose dropped tail contains a digit or a negation
      token, because that would silently discard a fact;
   5. do not add an ellipsis or any new word; the shortened text must be a
      contiguous prefix of the normalized answer.
7. Validate every candidate against the full discovered constraints
   (`maxlength`, `minlength`, `pattern`, non-empty) before entering it. Choose
   the longest candidate that passes. If no candidate passes, this pass makes
   no change and the existing correction/skip path handles the field.
8. Re-discover the control after any re-render (reuse `read_form` and
   `_marker_element`), confirm the replacement control still has the same
   constraints and that the candidate fits, then enter it with the existing
   `_fill_field`. Follow Task 20's discipline: one correction pass per blocked
   step, one fresh Next/Review retry, re-read validation afterwards, and never
   click **Submit application**.
9. If the shortened value is accepted and the step advances, continue the same
   application normally. Do not create a skip record or count the job as
   skipped.
10. If the value is still rejected, or no safe shortening exists, fall through
    unchanged to Task 20's remaining correction options and its log-and-skip
    path. Record the shortening attempt and its outcome in the skip record.
11. Show a concise progress message when shortening is used, for example:
    `Character limit: shortened rejected answer from 34 to 20 characters.`
    Do not include the answer text in the message or the log.
12. Do not hardcode any question text, field name, step position, control type,
    or character limit. Everything is discovered from the live step.

**Acceptance criteria**

- A required text field with a discovered `maxlength` of 20 that rejects a
  34-character answer is re-entered with a contiguous prefix of at most 20
  characters, the step is retried once, and the same application continues
  without a skip record when it is accepted.
- A counter-only limit (`555/20` or `15/20` with no native `maxlength`) is
  honoured exactly like a native limit.
- An answer already within the limit, or exactly at the limit, is not changed.
- Numeric fields and bare numeric answers are never truncated; `120000` with a
  3-character limit is left to type conversion/skip rather than becoming `120`.
- Negated answers are never truncated in a way that could remove the negation.
- Shortening never cuts in the middle of a word when a word boundary fits, and
  never splits an emoji/surrogate pair or a URL/e-mail/identifier when a
  character-boundary fallback is attempted.
- `minlength`, `pattern`, and non-empty checks are applied to the shortened
  value; a candidate that violates them is not entered.
- Shortening runs before the log-and-skip path and is bounded by the existing
  one-correction/one-retry budget. A still-rejected shortened value falls
  through to the existing Task 20 behaviour, with the skip record noting the
  limit, original/shortened lengths, whether entry was attempted, and the
  outcome (never the answer text).
- No submission is triggered; submission stays manual.
- The implementation reuses the existing validation/correction/navigation
  seams and does not introduce a parallel limit parser that can disagree with
  `detection.py`.
- Automated tests cover: native `maxlength`, counter-only limit, over/under/
  exact limits, whitespace normalization, word-boundary shortening, no
  word-boundary fallback, single long token, numeric no-truncation, negation,
  `minlength`/pattern rejection, UTF-16/emoji, still-rejected shortened value,
  audit/skip-record fields, and fall-through to the existing correction/skip
  flow.
- Live-browser verification on LinkedIn confirms the reported over-limit case
  end-to-end: an over-limit answer on a real Easy Apply field is shortened,
  accepted, and the same application continues to review/manual submission.
  Unit tests alone do not complete this subtask.

**Implementation notes**

- Put the shortening logic in a new module, for example
  `src/tools/linkedin_validation/length_limit.py` (pure candidate builder plus
  metadata-only planning), and its audit model in
  `src/state/text_shortening.py`. Add a small flow module (for example
  `length_flow.py`) for the live-control recheck and accepted/rejected outcome,
  mirroring `conversion_flow.py`. Keep every file under the 415-line limit.
- Reuse `constraints._within_constraints` for validation, `conversion_source`
  for the entered literal, `conversion_flow._LIVE_CONSTRAINTS` (or a shared
  live-constraint helper) for the replacement control, and the existing
  `correction.py` / `navigation.py` one-pass retry. Do not duplicate the
  correction budget.
- Extend `ValidationFailure` with a `text_shortening_attempts` list and the
  Task 20 skip record with the same field. Records are metadata-only:
  `question`, `limit`, `original_length`, `shortened_length`, `attempted`,
  `outcome` (`not_possible`, `entry_failed`, `entered`, `accepted`, `rejected`,
  `not_retried`). Older payloads must load with an empty list.
- This subtask intentionally authorises dropping **trailing** content for an
  over-limit free-text answer. That is the one exception to Task 20 / BUG-105's
  blanket "never truncate into a different meaning" rule. It does not relax the
  safeguards for numbers, negations, units, or leading facts. Update
  `docs/task20-validation-recovery.md` and
  `docs/task25-answer-type-conversion.md` (or add
  `docs/task25-character-limit-recovery.md`) to state the exception and the
  limits.
- Review interrelated code when implementing: `detection.py` counter parsing,
  `constraints.py`, `conversion_flow.py`, `correction.py`, `navigation.py`,
  `skip.py`, `src/state/validation.py`, `src/state/type_conversion.py`, Task 24
  required-answer routing, Task 26 completion policy, progress messages,
  `README.md`, tests including monkeypatch targets, and the existing
  `test_task20_constraints.py::test_character_limit_must_not_truncate_factual_numbers`
  expectations (keep the numeric assertion; the text-clipping expectation is
  the behaviour this subtask changes).
- Add a Chromium integration test (for example
  `tests/integration/test_task25_length_limit_live.py`) using a local fixture
  with a real input, a visible `N / M` counter, a server-style rejection, a
  re-render, and one retry. Extend `scripts/verify_task25_linkedin.py` or add a
  verifier for the real-site check.
- Log any bug found/fixed during implementation under
  `known Bugs/task_25_bugs.md` and update `known Bugs/bug_log.md` in the same
  change, with symptom, root cause, fix, status, and evidence.
- Keep Subtask 25.1 and Task 25 🟡 In progress until implementation,
  live-browser verification, and the user's explicit confirmation. Mark it
  ✅ Done only in this file (the index tracks Task 25 as a whole) after those
  conditions are met.
