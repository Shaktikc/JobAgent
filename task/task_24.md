# Task 24 — On a required-question validation error, answer it or ask the human, then continue without crashing

**Status:** 🟡 In progress

**Goal:** When an Easy Apply step reports a required-question validation error
(for example **"This field is required"**) after the agent fills the step and
clicks **Review**/**Next**, do not stop or crash. Find the blocking required
question, try to answer it automatically from the agent's existing grounded
sources, and if no grounded answer exists, ask the human through Task 5's
browser banner. Apply the answer, re-verify the step, and continue the same
application. If no answer can be obtained, stop/skip safely with a clear note
and a durable log — never with an uncaught exception.

**Reported example**
- Screenshot: `C:/Users/shakt/OneDrive/Pictures/Screenshots 1/Screenshot 2026-11-04 195201.png`.
- LinkedIn Easy Apply — **Apply to Bluebird**, step **1/20**.
- The required radio question **"Do you use AI coding tools daily in your
  work?\*"** is left unanswered; the other questions on the step are answered.
- After **Review**, LinkedIn shows **"This field is required"** under that
  question and the agent does not recover: the form stays open, nothing asks
  the human for this answer, and the run stops.

**Why this happens today (verify live; do not assume)**
- `_fill_step` in
  `src/tools/linkedin_easy_apply_fill/field_filling.py` leaves a required
  question unknown when the LLM chooser does not decide and Task 5's `ask`
  returns `None` (human disabled, skipped, or timed out).
- `read_rejections` in `src/tools/linkedin_validation/detection.py` matches
  wordings such as `invalid input` and `required field`, but **not** the exact
  visible wording **"This field is required"**. A radio/checkbox group's message
  can also sit outside the immediate parent chain the reader inspects, so the
  issue may not be associated with the group.
- Without a recognised validation issue, `finish_advance` reports "form did not
  advance"; `classify_failure` then maps the unanswered required field to
  `required_question_unanswered`, which is deliberately treated as
  non-recoverable — so the run stops instead of asking the human and retrying.

**Dependencies**
- Task 4's fill/walk and Task 5's ask-the-human flow.
- Task 10's stored-answer chooser and Task 12's job-context chooser.
- Task 20's validation detection, one-correction retry, skip journal
  (`data/invalid_input_skips.json`), and safe close/continue path.
- Task 21's required-only policy (never ask about an unstarred question).
- Task 26's answer-completion policy (delegate the wait/save rules; do not
  duplicate them here).
- Task 25's type-conversion policy when an answered value is rejected for its
  format rather than for being missing.

**Expected behavior**
1. Detect the current step's visible validation state after filling and after
   each **Review**/**Next** attempt. Recognise at least:
   - a required control or group left unanswered, including the exact wording
     **"This field is required"** and equivalent "required", "please select/
     enter/provide", `aria-invalid="true"`, `:user-invalid`, `role="alert"`, and
     inline error/feedback messages;
   - group-level messages for radio/checkbox questions where the message is a
     sibling or ancestor of the option controls, not a descendant of the input.
   Hidden, unrelated, or another question's feedback must never be treated as
   this question's error.
2. Map every detected issue to its own question label/group heading and
   control(s) by reading the live DOM. Do not rely on fixed step numbers,
   positions, field names, or question text.
3. Keep Task 21's rule: only a question whose own visible label carries `*`
   (or an equivalent visible required marker) may be answered or asked about.
   An unstarred question is never auto-answered or prompted.
4. For each blocking required question, resolve an answer in this order:
   1. an answer the step already holds (pre-filled/committed controls);
   2. the existing grounded answer sources — stored answers (Task 10) and
      job-context/selected-resume answers (Task 12), through the existing
      chooser;
   3. if the chooser cannot decide, Task 5's existing banner/answer flow for
      that exact question, with its correct markers/name/options, waiting for
      the human;
   4. never invent, guess, default, or reuse an unrelated stored answer.
5. Apply the chosen answer to the real control with the existing fill actions
   (radio option click, checkbox-group tick, select option resolution, text
   input events). Re-discover the control after any React re-render; verify the
   control really holds the answer before retrying navigation.
6. Retry the step's **Review**/**Next** once after applying answers, then
   re-read validation. If the error cleared and the step advanced or reached
   review, continue the same application normally — do not log or count it as
   skipped. Keep the existing one-correction discipline for genuinely invalid
   (not merely missing) values and delegate type fixes to Task 25.
7. Bound the recovery: at most one automatic resolution pass per question and
   one human prompt per question per step, with a small overall cap per step.
   Never click **Submit application**, never loop indefinitely, and never wait
   when `AUTOJOB_SESSION_ASK_HUMAN=false`.
8. If the human skips/times out, the answer cannot be applied, or LinkedIn still
   reports the error after the bounded retry, do **not** crash. Fall back to
   Task 20's safe path: persist a skip record with the direct job link, the
   question and visible message, whether an automatic/human answer was tried,
   and why it failed; close Easy Apply and continue with the next eligible job.
   If logging or closing itself fails, stop safely with that reason and the
   preserved link.
9. Contain failures: any exception from DOM reads, answer resolution, banner
   display, control clicks, or navigation must be caught and converted into an
   honest outcome/note. Validation recovery is not a structural crash, so it
   must never propagate to the graph crash guard or trigger self-healing.
10. Show concise progress messages naming the question and the action:
    answering automatically, asking the human, retrying after the answer, or
    skipping with the saved link.

**Acceptance criteria**
- The reported Bluebird scenario is recovered: the required radio question is
  either answered automatically from a grounded source or the Task 5 banner
  asks the human for it; once answered, **Review** proceeds and the same
  application continues without a skip record.
- Every required question remains eligible regardless of topic or control type
  (text, textarea, select, radio, checkbox group); unstarred questions stay
  untouched and are never prompted (Task 21).
- Human answers are read/applied exactly as Task 5 already does; the recovery
  never answers on the human's behalf, never stores a partial answer, and
  respects Task 26's completion rules.
- A question the agent cannot answer and the human does not answer ends in a
  clear, safe stop/skip with a durable direct job link — no traceback, no
  uncaught exception, no self-healing retry for a validation outcome, and no
  submission.
- The recovery is bounded, re-discovers controls after re-renders, and never
  repeats the same prompt blindly.
- Relevant automated tests cover: exact "This field is required" detection;
  group-level message association; automatic answer success; human answer
  success; human skip/timeout; still-rejected answer; missing required marker;
  unstarred question exclusion; DOM/banner/navigation exceptions; bounded
  attempts; skip-record contents; and continuation without a crash.
- Live-browser verification on a real LinkedIn Easy Apply form reproduces the
  screenshot state (a required radio left blank, Review shows "This field is
  required") and confirms both paths: answering (automatic or human) advances
  the form, and an unanswerable question skips gracefully with the log and no
  crash. Unit tests alone do not complete this task.

**Implementation notes**
- Creation only is authorized now; implementation and runtime verification are
  pending.
- Start from the live DOM and the real failure, not from the screenshot alone.
  Reuse existing seams: `src/tools/linkedin_easy_apply_fill/form_walk.py`
  (`_blocking_questions`, `_fill_step` callers), `field_filling.py`,
  `required_only.py`, `src/tools/linkedin_validation/` (`detection.py`,
  `correction.py`, `navigation.py`, `skip.py`), and `src/tools/linkedin_ask_human/`.
  Prefer a new module (for example a required-question recovery helper) instead
  of growing an existing file past the 415-line limit.
- Review interrelated code when implementing: Task 4/5 outcome models, Task 20
  skip schema and accounting, `classify_failure`/`is_recoverable` in
  `src/tools/self_healing/fingerprint.py`, Task 21 filtering, Task 25 type
  conversion, Task 26 answer completion, progress/status messages, tests
  (including monkeypatch targets), `.env.example`, and `README.md`.
- Log any bug found/fixed during implementation under
  `known Bugs/task_24_bugs.md` and update `known Bugs/bug_log.md` in the same
  change, with symptom, root cause, fix, status, and evidence. Create the file
  without waiting for approval.
- Keep Task 24 🟡 In progress in this file and `task/task.md` while it is
  being worked on. Mark it ✅ Done only after implementation, live-browser
  verification, and the user's explicit confirmation that the task works.
