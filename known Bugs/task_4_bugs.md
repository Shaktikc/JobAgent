# Task 4 — Bugs (fill the Easy Apply form)

Bugs whose root cause is in **Task 4**: enumerating the Easy Apply form, filling
known controls, attaching the resume, and advancing the steps.

See [`bug_log.md`](bug_log.md) for the master index and the entry format.
Status: 🟢 Fixed · 🟡 Fixed (superseded) · 🔴 Open · ⚪ Won't fix

| ID | Symptom (short) | Status | Fix commit(s) |
|----|-----------------|--------|---------------|
| BUG-002 | unreadable form silently looked empty → every field `NEEDS_REVIEW` | 🟢 Fixed | `24d381f` |
| BUG-003 | fill only touched the first modal step (`1/4` pages) | 🟢 Fixed | `24d381f` |
| BUG-005 | no screenshot on a failed application | 🟢 Fixed | `14719e9` |
| BUG-022 | inline hashed-class Easy Apply form not found | 🟢 Fixed | `84b0bb5` |
| BUG-023 | first matching modal was a hidden unrelated dialog | 🟢 Fixed | (Task 4 modal fix) |
| BUG-032 | walk stopped at a field-less review step ("form did not advance") | 🟢 Fixed | (uncommitted) |
| BUG-034 | "Experience on AI?" reported unknown despite the store covering it | 🟢 Fixed | (uncommitted) |
| BUG-035 | checkbox group: the human's tick was never saved (one question per option) | 🟢 Fixed | (uncommitted) |
| BUG-042 | stopped at **Review** (next step not rendered yet); optional unfilled field failed the run | 🟢 Fixed | (uncommitted) |

---

### BUG-002 — an unreadable form silently looked empty

- **Symptom:** when the agent produced no `FormField`s, `open_and_read_fields`
  returned `()`, every answer became `NEEDS_REVIEW`, and the job looked like an
  empty form.
- **Root cause:** a broken read was indistinguishable from an empty form.
- **Fix:** raise `FillError`; `_node_answer` persists `JobStatus.FAILED` before
  propagating, mirroring `_node_fill`.
- **Evidence:** `tests/unit/test_fill_read_fields.py` (8),
  `tests/unit/test_browser_agent_tasks.py`. Commit `24d381f`.

### BUG-003 — the fill only touched the first modal step

- **Symptom:** the live Easy Apply form was `1/4 pages`; only step 1 was filled.
- **Root cause:** `READ_FORM_TASK` and the fill task never advanced the modal.
- **Fix:** both advance with **Next/Continue** through every step and still never
  submit.
- **Evidence:** `tests/unit/test_fill_read_fields.py`. Commit `24d381f`.

### BUG-005 — no screenshot on a failed application

- **Symptom:** the requirement "a PNG for every application" was violated on
  failure — screenshots were captured only on success.
- **Root cause:** `fill_application` captured only the success path.
- **Fix:** capture the failing form (`tag='failure'`) before re-raising; a
  screenshot error is logged without masking the original failure.
- **Evidence:** `tests/unit/test_fill_agent.py`. Commit `14719e9`.

### BUG-022 — the inline hashed-class Easy Apply form was not found

- **Symptom:** on the AI/semantic job view the inline full-page application form
  was not recognised, so nothing was filled.
- **Root cause:** LinkedIn has two layouts — the classic artdeco modal and an
  inline form whose classes are hashed. The queries only matched the classic
  modal.
- **Fix:** `FIND_APPLY_ROOT_JS` defines `findApplyRoot()`, used by the enumerate /
  resume-options / buttons queries, to find either layout (classic dialog, or an
  inline form anchored on a phone/email control or "Apply to <company>" heading).
  `_with_apply_root` injects it into the self-contained Task 4 queries.
- **Evidence:** `src/tools/browser.py`, `src/tools/linkedin_easy_apply_fill.py`,
  `src/tools/linkedin_job_selection.py`;
  `test_task4_fills_inline_hashed_class_form`. Commit `84b0bb5`.

### BUG-023 — the first matching modal was a hidden unrelated dialog

- **Symptom:** the fill walk enumerated zero fields and filled nothing.
- **Root cause:** an unrelated hidden `.artdeco-modal` (e.g. "Save this job")
  appeared before the Easy Apply modal, and the lookup used the *first* match.
- **Fix:** prefer the Easy Apply dialog, then the first **visible** dialog holding
  form controls or "Easy Apply" text.
- **Evidence:** `src/tools/browser.py` (`FIND_APPLY_ROOT_JS`);
  `test_task4_ignores_a_hidden_dialog_before_the_easy_apply_modal`.

### BUG-032 — the walk stopped at a field-less review step ("form did not advance")

- **Symptom:** on a multi-step Easy Apply form the walk stopped at a profile
  **review/edit** step (e.g. "Work experience", shown as `3/7 pages`) with the
  note `form did not advance to a new step`, even though Next was enabled and more
  steps remained. Log tail: `fill: no resume control found on this form step;
  form did not advance to a new step; stopping before Submit`.
- **Root cause:** `_form_signature` fingerprinted a step from
  `modal.querySelector('h3')` plus the enumerated fields. On LinkedIn the first
  `<h3>` is the modal title (`Apply to <company>`, constant), and review/edit steps
  hold **no fillable controls**, so two consecutive review steps produced an
  identical fingerprint. The walk wrongly concluded Next had not advanced and
  stopped before the terminal step.
- **Fix:** `_ENUMERATE_FORM_QUERY` now also returns a `step` identity and
  `_form_signature` includes it, so field-less steps are told apart. The identity
  is the modal's progress indicator ("3/7 pages"), its headings, **and a hash of
  the modal's whole visible text**. The first attempt (progress + headings only,
  commit `97c157d`) was insufficient on the live page: the progress/step-heading
  signal did not change between the review steps, so the walk still stopped. The
  whole-text hash always changes with the step's rendered content. (Also split
  `form_queries.py` into the `form_queries/` package — `scripts.py` + `readers.py`
  — per the file-size rule.)
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_easy_apply_fill/form_queries/scripts.py`
  (`_ENUMERATE_FORM_QUERY` step identity: progress + headings + visible-text hash),
  `src/tools/linkedin_easy_apply_fill/form_queries/readers.py` (`read_form`),
  `src/tools/linkedin_easy_apply_fill/form_walk.py` (`_form_signature`,
  `_task4_on_page`, which logs `Task 4: step N: ... step_id=...`);
  `tests/unit/test_task4_review_steps.py` (2 tests; both fail without the fix);
  live-browser reproduction with the progress indicator placed *outside* the modal
  and the step titles as plain `<div>`s (so only the text hash distinguishes the
  steps): `step_id` `text:1029807389` → `text:3706210911` → `text:2325457445`,
  `steps_advanced` 2, `reached_terminal_step` True. Commit `97c157d` (first,
  insufficient attempt) + (uncommitted enhancement).

### BUG-034 — "Experience on AI?" reported unknown even though the store covered it

- **Symptom:** the Easy Apply form asked **"Experience on AI? [Yes/No]"** while
  `data/answers.json` already held
  `"how many years of work experience do you have with artificial intelligence (ai)": "5"`.
  No stored value was literally `"Yes"`, so Task 4.1's select-only chooser picked
  none and the run reported *"AutoJobApply does not know this answer"* and handed
  the question to Task 5 — even though the answer ("Yes") is plainly entailed by
  the stored entry. Every similar rewording/entailment case was affected.
- **Root cause:** `src/tools/llm_answers.py` (Task 4.1) could only **copy** a stored
  answer string. Its `parse_decision` resolves `matched_key` against the store and
  rejected everything else, so a question whose answer was *derivable* from the
  store had no way to be answered.
- **Fix:** Task 10 adds a match-or-derive chooser
  (`src/tools/llm_answer_reasoning.py`) that returns the answer plus the stored
  `source_keys` it used, and a pure validator (`validate_decision`) that rejects
  any answer whose cited sources do not exist, any derive the cited values do not
  entail (positive years ⇒ "Yes"; zero ⇒ "No"; a non-numeric "No" cannot entail
  "No" for a different question), and any choice answer that maps to none of the
  question's options. A rejected decision stays *unknown* and flows to Task 5.
  `QuestionDecision` gained `source_keys`/`derived`/`source_summary` and
  `FormField` gained `derived`/`source_keys` for the audit trail; accepted derives
  are cached in `data/derived_answers.json` (never in `answers.json`), and Task 9's
  `LLM:` line names the source and says matched vs derived.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/llm_answer_reasoning.py` (chooser + `validate_decision`),
  `src/tools/derived_answers.py` (the derived-answer cache),
  `src/tools/llm_answers.py` (`QuestionDecision` provenance),
  `src/tools/linkedin_easy_apply_fill/form_walk.py` (builds the reasoning chooser),
  `src/tools/linkedin_easy_apply_fill/field_filling.py` (`_decide` status + record),
  `src/state.py` (`FormField.derived`/`source_keys`), `src/nodes/fill.py` (run log);
  `tests/unit/test_llm_answer_reasoning.py` (27 tests) and
  `tests/unit/test_llm_answers.py`. Live browser run (real Chromium + real
  `deepseek/deepseek-v4.1-flash`): the fixture's "Experience on AI? [Yes/No]" filled
  **Yes** with `sources=['how many years of work experience do you have with
  artificial intelligence (ai)']`, the unknown salary question stayed for Task 5,
  `answers.json` was unchanged, the derived cache was written, and a second pass
  answered from the cache with no LLM call (uncommitted).

### BUG-035 — a checkbox group was one question per option, so the human's tick was never saved

- **Symptom:** on a "select all that apply" screening question (e.g. "Before you
  applied, where did you first encounter Propeller?*" with options LinkedIn Job Ad,
  LinkedIn Social Post, Glassdoor, ...) the Task 5 banner asked about an **option**
  ("LinkedIn Social Post") instead of the question, and ticking a checkbox did not
  save the answer. Live reproduction: the human ticked *Glassdoor* while the banner
  asked another option; nothing was captured for the question, and the run wrote
  **five bogus entries** instead — one per option text, each holding the ticked
  value (`'linkedin job ad': 'Glassdoor'`, `'glassdoor': 'Glassdoor'`, ...), so the
  real question was never learned and the agent asked it again next time.
- **Root cause:** a checkbox question is a **group** (all options share one
  question and one answer), but the fill enumerated every option as its own
  question (`_ENUMERATE_FORM_QUERY` could not read the group's question because
  LinkedIn's container classes are hashed and the option's own text won), and
  `_fill_step` handled each option independently. Task 5's answer watcher was
  therefore scoped to a **single** option's marker, so ticking any other option
  was out of scope and never captured. `_fill_field` also only ever ticked a box
  for a yes/no answer, so a stored multi-select answer could not tick anything.
- **Fix:** a checkbox question is answered as one group. A new module
  `src/tools/linkedin_easy_apply_fill/checkbox_groups.py` resolves the group's
  question in the page (`GROUP_QUESTION_JS`, injected into the enumeration query,
  replacing the option-text reading), reads **every** ticked option after a short
  settle (`READ_GROUP_TICKS_JS`), and applies an answer by ticking the matching
  boxes. `_fill_step` groups the options by their shared name/question, asks the
  LLM and then the human **once** with **all** the group's markers in scope (so a
  tick on any option is captured) and records one `FormField` for the group.
  Options already ticked are never re-clicked (`check()` on a
  `[role="checkbox"]` wrapper would untick them), the joined selection is stored
  under the group question, and an answer that maps to no option is left unknown
  for Task 5 rather than guessed.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_easy_apply_fill/checkbox_groups.py`,
  `.../form_queries/scripts.py` (`groupLabel` + `_with_apply_root` injection),
  `.../field_filling.py` (checkbox branch, `_fill_field` label tick);
  `tests/unit/test_task4_checkbox_groups.py` (13 tests; the key one,
  `test_fill_step_asks_once_for_the_whole_checkbox_group`, asked the option text
  four times before the fix). Live browser runs (real Chromium): variant A (no
  aria attributes), variant B (option `aria-label` = question), and variant C
  (per-option `name`s, so the shared *question* is the group key) all saved the
  group question once — `'before you applied, where did you first encounter
  propeller': 'Glassdoor, YouTube'` — kept the ticks on the page, and a stored
  multi-select answer ticked both matching boxes with no human prompt
  (uncommitted).

### BUG-042 — the walk stopped at Review before the review step rendered

- **Symptom:** on the last form step, clicking **Review** ended the run with
  `fill: form did not advance to a new step` even though Review was there; the
  run also reported `fill: some known fields were not filled` without naming the
  field.
- **Root cause:** after clicking Next/Review the walk read the form **once,
  immediately**, and treated the unchanged step as a failed advance. LinkedIn can
  render the review step a moment later, so the first read still saw the old step.
  Separately, any known-but-unfilled field (even an optional one) failed the run,
  while a required field that could not be filled was never named.
- **Fix:** after a navigation click the walk now polls for the step signature to
  change (up to the existing easy-apply timeout) and logs the new step when it
  appears. Only **required** unknown/unfilled fields block the walk or fail the
  node, and they are named with their error. Optional unfilled fields are logged
  as `known but not filled` and do not fail the run.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_easy_apply_fill/form_walk.py`
  (`_blocking_questions`, the advance wait), `src/nodes/fill.py` (required-only
  errors + unfilled log); `tests/unit/test_task4_review_steps.py`
  (`test_task4_waits_for_a_slow_review_step_to_render`),
  `tests/unit/test_graph.py`
  (`test_fill_node_does_not_fail_on_an_optional_unfilled_field`,
  `test_fill_node_names_the_required_fields_that_block_review`),
  `tests/integration/test_fill_form_live.py`
  (`test_task4_waits_for_an_async_review_step`). Live browser fill suite: 11/11.
  Commit: (uncommitted).
