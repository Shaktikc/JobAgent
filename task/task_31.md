# Task 31 — Take a second look in answers.json before asking the human about an unknown question

**Status:** 🟡 In progress

**Goal:** When a required Easy Apply question is about to be handed to Task 5
because the automatic answer chooser found no answer, make **one independent
second attempt** against the current `data/answers.json` store before showing the
human banner. If the second attempt finds a grounded answer — or an exact stored
answer the first pass missed — fill it and do **not** ask the human. If the second
attempt also finds nothing, ask the human exactly once, as today.

In short: never ask the human for an unknown question until the agent has looked
at the answer store a second time.

**Reported problem**

- The LLM answer chooser can miss an answer that is already in
  `data/answers.json` — for example when the question is paraphrased, uses an
  abbreviation or synonym, or the answer is entailed by a related stored entry.
- Once the first chooser call returns unknown, the fill immediately opens Task 5's
  browser banner. The human is asked for an answer the agent already knows, which
  wastes the human's time and can look like the agent ignored its own store.
- There is currently no second look and no deterministic exact-key safety net on
  the normal fill path: if the one model call misses, the question is treated as
  unknown even when the store literally contains it.

**Scope**

- Task creation only is authorized now; implementation and runtime verification
  are pending.
- One extra automatic attempt per question per form step, only when the first
  automatic attempt returned no usable answer and a human prompt would otherwise
  follow.
- Applies to every human-prompt path for form questions:
  - normal fill: text, textarea, select, radio, and checkbox groups;
  - Task 24 required-answer recovery.
- The second attempt covers the current in-memory store (loaded from
  `data/answers.json`) and may use the same match-or-derive rules as Task 10.
- Preserve Task 12's safety rule: a likely job-specific free-text question that
  the context chooser explicitly marks `job_specific` and cannot ground must not
  be retried against stale store entries. It still goes to the human.
- Preserve Task 21 (required-only questions), Task 24 (bounded attempts),
  Task 25 (type conversion), and Task 26 (save only after the human finishes).
- No change to submission behaviour. This task never clicks **Submit
  application**.

**Dependencies**

- Task 4.1/10's chooser and validator:
  - `src/tools/llm_answers.py` (`QuestionDecision`, `AnswerChooser`);
  - `src/tools/llm_answer_reasoning.py`
    (`ReasoningAnswerChooser`, `parse_reasoning_reply`, `validate_decision`);
  - `src/tools/job_context_answers/chooser.py`
    (`ContextAwareAnswerChooser`, `build_fill_chooser`).
- Task 5's human prompt:
  - `src/tools/linkedin_ask_human/flow.py` (`ask_human_for_answer`);
  - `src/tools/linkedin_validation/required_answers.py` (`AnswerAttempts`).
- Task 10.3's derived-answer cache:
  - `src/tools/derived_answers.py`.
- Task 30's token accounting:
  - `src/tools/token_usage/runtime.py` (`tracked_completion`).
- The answer store:
  - `src/tools/answers.py` (`load_answers`, `normalize_question`).

**Inputs**

- The current question, its field type, and its allowed options.
- The current in-memory answer store (the same dictionary the fill is already
  using; it includes answers added during this run).
- The first `QuestionDecision` (normally unknown).
- The configured answer model (`answer_llm_settings(settings)`), if any.
- `notify` / Task 9 status, for concise progress lines.

**Expected behaviour**

1. **First attempt unchanged.** Run the existing chooser once, exactly as today.
   If it returns a usable answer, fill it normally. Do not make a second call.
2. **Decide whether a second look is allowed.** Take the second look only when
   all of these are true:
   - the first decision is not usable for this question (no answer, or an
     answer that maps to none of the current choice options);
   - a human prompt would otherwise happen;
   - the in-memory store is non-empty and available;
   - an answer model is configured (there was a first model attempt to retry);
   - the first decision is not a deliberate job-context rejection
     (`decision.job_specific is True` and undecided), because Task 12 forbids
     reusing stale store prose for such a question;
   - no second look has already been made for this question in this step.
3. **Second look, part A — exact stored answer.** Normalize the question with
   `normalize_question` and check the current store for an exact key. If present:
   - reject an empty, placeholder, or question-echo value;
   - validate it against the current control (see point 5);
   - return a copied decision with `matched_key`, `source_keys=[key]`,
     `source_summary`, and a marker that it came from the second look.
   This path must not call the model and must never write to `answers.json`.
4. **Second look, part B — one focused model re-read.** If no usable exact key
   exists, make exactly one new LLM call with a dedicated second-look prompt:
   - include the question, field type, allowed options, and the complete current
     store;
   - state that the first pass already searched the store and found no grounded
     answer, so the model must look again for a missed entry;
   - ask it to consider paraphrases, abbreviations, synonyms, and related
     experience/education/authorization entries, and to match or derive only
     from the store;
   - require `source_keys`; reject an answer with no existing cited source;
   - never use outside knowledge and never invent;
   - return an empty answer and empty `source_keys` when nothing supports it.
   Parse with the existing reasoning parser and validate with the existing
   grounding/option rules. A derived answer is cached best-effort in
   `data/derived_answers.json` exactly as Task 10.3 does; it is never written to
   `data/answers.json`.
5. **Control-specific validation.**
   - text/textarea: the answer must be non-empty and grounded;
   - radio/select: the answer must map to one of the question's options;
   - checkbox group: the answer must resolve to at least one of the group's
     option labels (or be a valid single-checkbox yes/no answer); a
     comma-separated selection is allowed;
   - a stored answer that cannot be applied to the current control is not a
     usable second-look answer; fall through to the human.
6. **Second look succeeded.** Fill the field through the normal path, record
   `answered_by="llm"` with the normal provenance, and mark the decision/field as
   coming from the second look. Show a concise status line such as
   `Second look found a stored answer for "<question>"; using it.` Do **not**
   show the human banner, do **not** increment the human-asked counters, and do
   **not** persist the answer into `data/answers.json`.
7. **Second look failed.** Proceed to the existing human prompt exactly once.
   Record in the run log/audit that the first pass and the second look both found
   no grounded answer, with a concise reason. Never loop, never show the banner
   twice, and never call the model again for the same unknown question in the
   same step.
8. **Bounded and contained.**
   - The maximum is two automatic attempts per question per step: the existing
     first attempt plus one second look. Existing Task 24 caps remain in force.
   - A timeout, exception, missing client, corrupt store, or invalid second-look
     reply must be swallowed and must fall through to the human prompt without
     crashing the fill.
   - The second look must not block the run for an unbounded time; use the
     configured answer-model timeout.
9. **Metrics.** Every second-look LLM call must go through
   `tracked_completion` so Task 30 counts its prompt/completion tokens and cost.
10. **No model configured.** Keep today's behaviour: no first model attempt, no
    second model attempt, and the question goes to the human. Exact-only fallback
    outside the model path is out of scope for this task.
11. **Job-specific exception.** Keep Task 12's precedence and safety rules. An
    exact human answer still wins in `ContextAwareAnswerChooser`; a likely
    job-specific question that the context chooser cannot ground goes to the
    human rather than being retried against an old similar store entry.

**Implementation notes**

- Prefer a new module, for example `src/tools/answer_second_look.py`, containing:
  - an exact normalized-key lookup that returns a grounded `QuestionDecision`;
  - a dedicated second-look prompt and parser/validator;
  - one async entry point such as
    `second_look_for_answer(settings, answers, question, field_type, options,
    first_decision=..., notify=...) -> QuestionDecision`.
  If the module grows past the 415-line limit, split it into a package by
  concern (lookup, prompt, retry, exports).
- Integrate the retry in `AnswerAttempts.choose` in
  `src/tools/linkedin_validation/required_answers.py`. That method is the single
  bounded automatic-attempt path used by both normal filling
  (`_fill_step(chooser=attempts.choose)`) and Task 24 recovery
  (`recover_required`). Doing it there guarantees every form path gets the
  second look before `AnswerAttempts.ask` shows the banner.
  - Do not add the retry inside `ask_human_for_answer`; that would duplicate the
    attempt and could show a banner after a second look already succeeded in
    another layer.
  - `AnswerAttempts.choose` must still make only one *external* automatic call
    decision per question/step; the second look is internal to that decision and
    remains bounded.
  - Add a small control-fit helper (or reuse the existing option matchers) so a
    first decision that chose an answer that matches none of the current
    radio/select options is treated as unresolved and gets the second look.
    Checkbox groups need the multi-select rule, not a single-option match.
- Reuse existing logic rather than duplicating it:
  - `normalize_question` for the exact key;
  - `build_reasoning_messages` as the base user message (then replace or extend
    the system instruction for the second look);
  - `parse_reasoning_reply` and `validate_decision` for grounding, options, and
    derive entailment;
  - `save_derived_answer` / `supported_by_store` for the derived-answer cache;
  - `answers_match` / `selected_options` for control-specific mapping;
  - `tracked_completion` for the LLM call.
- Add provenance fields so the decision is explainable:
  - `QuestionDecision.second_look: bool = False` (or equivalent);
  - `FormField.second_look: bool = False`, copied by `record_decision`;
  - include `second look` in the audit line built by `src/nodes/fill.py`;
  - optionally add `second_attempted` / `second_attempt_found` to
    `RequiredAnswerAttempt` in `src/state/validation.py` and set them in
    `AnswerAttempts.choose` so `task4.validation.required_answer_attempts` shows
    the retry.
- Update every interrelated caller and test:
  - `src/state/outcomes.py` (`FormField`);
  - `src/state/validation.py` (`RequiredAnswerAttempt`, if extended);
  - `src/tools/job_context_answers/presentation.py` (`record_decision`);
  - `src/nodes/fill.py` (`_decision_line`);
  - `tests/unit/test_task23_llm_requests.py` (failed/ungrounded chooser tests
    currently expect one call; they must expect the second look);
  - `tests/unit/test_task24_answer_attempts.py` and
    `tests/unit/test_task24_recovery.py` (assert one human prompt and bounded
    attempts);
  - `tests/unit/test_llm_answer_reasoning.py` and
    `tests/unit/test_task12_job_context.py` (preserve job-specific precedence).
- Update `README.md`'s **Fill** bullet and safety notes to describe the one extra
  store look before the human prompt. Do not edit other task files.
- Keep every source file under the 415-line limit. A new file is created rather
  than growing `llm_answer_reasoning.py`, which is already near the limit.
- **Intentional supersession:** Task 4.1's note that there is "no deterministic
  exact-key fallback" still describes the *first* pass. This task adds a narrow
  exact-key check only to the second pass, after the semantic first pass fails.
  It does not replace meaning-based matching. Record the supersession here and in
  `README.md`; do not edit Task 4.1's task file.

**Tests**

Add focused unit tests (for example
`tests/unit/test_task31_answer_second_look.py`) covering:

- first pass decides → exactly one chooser call, no second look, no human prompt;
- first pass unknown, exact normalized store key exists → second look returns the
  stored answer without an LLM call; no human prompt;
- first pass unknown, no exact key, second LLM call finds a matched answer → two
  calls total, grounded sources, `second_look=True`;
- second LLM call derives a valid answer from related entries → accepted, cached
  in `derived_answers.json`, `answers.json` unchanged;
- second LLM call returns an invented/unsourced answer or an option that does not
  exist → rejected; the human is prompted once;
- both attempts unknown → exactly one human prompt, no loop, `second_look` audit
  recorded;
- second-look exception/timeout → falls through to one human prompt, no crash;
- empty store or no answer model → no second attempt, behaviour unchanged;
- job-specific `job_specific=True` unknown → no stale-store retry, one human
  prompt (Task 12 rule);
- checkbox group with a multi-select stored answer (for example `"A, B"`) →
  accepted and tickable;
- radio/select exact answer that does not match any option → not used, second
  model attempt or human prompt as appropriate;
- normal fill (`_fill_step`) and Task 24 recovery both use the retry before
  asking the human;
- Task 30 tracker records the second call when one is made.
- Update existing tests that assert one LLM call or one human prompt where the
  second look now intentionally adds a call. Do not delete or weaken the
  existing bounded-attempt assertions.

Run the full unit suite and lint.

**Live browser verification (required)**

- Run against a real LinkedIn Easy Apply form. Because a model miss is
  nondeterministic, use a verification harness that forces the first automatic
  pass to return unknown while leaving the second look and the real page intact
  (for example a wrapper chooser that returns unknown once, then delegates to the
  real second-look path). Confirm:
  1. a question whose answer is in `data/answers.json` is filled after the second
     look and **no** Task 5 banner appears; the terminal/panel shows the
     second-look line;
  2. a genuinely unknown question still shows exactly one Task 5 banner after
     both attempts, and the human's answer follows the Task 26 completion rules;
  3. a checkbox group with a stored multi-select answer is ticked correctly;
  4. a job-specific question that Task 12 rejects is not answered from an old
     store entry.
- Then run a normal live flow (`uv run autojob --no-dry-run` or the existing
  live harness) through at least one Easy Apply question and confirm ordinary
  answering and human prompting still work with no duplicate banners.
- Never click **Submit application**. Leave the browser open per the existing
  rules.
- If the live run reveals a real bug (for example the store was not consulted a
  second time, the second look asked the human twice, or it bypassed Task 12),
  log it in `known Bugs/task_31_bugs.md` and add/update the row in
  `known Bugs/bug_log.md` with symptom, root cause, fix, status, and evidence.
  Create the file without waiting for approval.

**Acceptance criteria**

- Before any Task 5 prompt for a form question, the agent makes exactly one
  extra automatic second attempt against the current `data/answers.json` store.
- The second attempt includes a deterministic exact normalized-key lookup and a
  focused second LLM re-read when needed.
- A second-look answer is used only when it is grounded in the store and fits the
  current control; no invented or outside-knowledge answer is ever filled.
- A question answered by the second look is filled without showing the human
  banner, without incrementing the human-asked counters, and without writing the
  generated answer to `data/answers.json`.
- A question the second look cannot answer still reaches exactly one human
  prompt; the banner is never shown twice for the same question/step.
- The retry is bounded to one extra attempt per question per step and is
  contained: model/API/store failures never crash or block the human fallback.
- Task 12's job-specific safety rule, Task 21's required-only rule, Task 24's
  bounded recovery, Task 25's type conversion, and Task 26's completion rules
  are preserved.
- Task 30 counts the second look's tokens and cost.
- Relevant unit tests, lint, and a live-browser check pass. A passing unit test
  alone does not complete this task.
- The task is marked 🟡 **In progress** when work begins and stays so until the
  user explicitly confirms it works.
