# Task 5 — Bugs (ask the human for unknown answers)

Bugs whose root cause is in **Task 5**: pausing for the human on a question the
agent cannot answer, remembering the answer, and surfacing what a human must
review.

See [`bug_log.md`](bug_log.md) for the master index and the entry format.
Status: 🟢 Fixed · 🟡 Fixed (superseded) · 🔴 Open · ⚪ Won't fix

| ID | Symptom (short) | Status | Fix commit(s) |
|----|-----------------|--------|---------------|
| BUG-006 | unrecognized required fields dropped from review | 🟢 Fixed | `14719e9` |
| BUG-024 | pre-filled controls (Email/Phone) wrongly asked about | 🟢 Fixed | `4eee839`/`99265a0` |
| BUG-025 | empty "Use answer" silently marked the question skipped | 🟢 Fixed | `2b60465` |
| BUG-026 | banner input vs. typing in the real form field | 🟡 Fixed (superseded) | `99265a0` |
| BUG-037 | a `<select>` prompt ("Select an option") was saved as the answer, then leaked into the next question | 🟢 Fixed | (uncommitted) |

| BUG-082 | a radio option's aria-label (the question) was saved as the answer | 🟢 Fixed | (uncommitted) |

---

### BUG-006 — unrecognized required fields dropped from review

- **Symptom:** four extra required questions vanished from the human review.
- **Root cause:** `reconcile_outcome` dropped agent-reported `unfilled_fields`
  that were never explicitly asked about.
- **Fix:** surface every unrecognized field as `NEEDS_REVIEW`.
- **Evidence:** `tests/unit/test_fill_agent.py`. Commit `14719e9`.

### BUG-024 — pre-filled controls were wrongly asked about

- **Symptom:** a real run paused on LinkedIn's pre-filled *Email address* and
  *Phone country code* selects (and could not set a select from free text).
- **Root cause:** controls the form already filled were treated as unknown.
- **Fix:** accept a pre-filled select/radio/text control as-is (no prompt, no
  overwrite); match a `<select>` answer to an option's visible text as well as its
  value; show the allowed choices in the banner.
- **Evidence:** `src/tools/browser.py`, `src/tools/linkedin_easy_apply_fill.py`;
  `tests/unit/test_browser_tools.py` ("pre-filled control skipped", "select label
  mapped to option value"). Commits `4eee839` / `99265a0`.

### BUG-025 — an empty "Use answer" silently skipped the question

- **Symptom:** clicking **Use answer** with an empty box marked the question
  skipped.
- **Root cause:** an empty submit was treated as a skip.
- **Fix:** keep the banner open and re-prompt ("please type an answer … or click
  Skip"); **Skip** remains for an intentional skip.
- **Evidence:** `src/tools/browser.py` (`ask_human_for_answer`). Commit `2b60465`.

### BUG-026 — banner input vs. typing in the real form field

- **Symptom:** the banner had its own input; the answer was not always applied to
  the actual form control.
- **Root cause:** the answer was read from the banner input rather than the field
  the human edits.
- **Fix (first):** redesign the banner to instruct the human to type in the form
  field, watch the form for the value (`_WATCH_FORM_ANSWER_JS` /
  `_READ_FORM_ANSWER_JS`), and read the edited value + completion state.
- **Status:** 🟡 **Fixed (superseded)** — a later change simplified the banner; see
  the current `ask_human_for_answer`.
- **Evidence:** `src/tools/browser.py` (`_SHOW_UNKNOWN_JS`,
  `_WATCH_FORM_ANSWER_JS`, `_READ_FORM_ANSWER_JS`, `ask_human_for_answer`);
  `test_task5_pauses_for_the_human_and_remembers`. Commit `99265a0`.

### BUG-037 — a `<select>` prompt ("Select an option") was saved as the answer

- **Symptom:** after a Lendi Group application, `data/answers.json` held
  `"which of the following statements best describes your right to work in
  australia and new zealand": "Select an option"` and
  `"what are your salary expectations (base salary)": "Select an option"` — the
  dropdown's **prompt**, not the choice the human made. The same run then stored
  the right-to-work option text against the *next* question ("Have you ever been
  employed by the government…").
- **Root cause:** Task 5's answer watcher read a `<select>`'s **selected option
  text** with no placeholder check. LinkedIn's prompt option is `disabled` with
  `value=""` and text "Select an option"; the moment the human clicked the select
  to open its dropdown (or clicked away without choosing) the watcher recorded
  "Select an option" with `done=true`, so the flow stored it immediately. A second
  defect made it spread: `_READ_FORM_ANSWER_JS` trusted the last recorded value
  (`state.value`) regardless of which question's markers it was recorded for, so it
  could answer the next question.
- **Fix:** the watcher and the reader now share an `isSelectPrompt()` check (prompt
  text, or a disabled option with no value) and never read the prompt as an
  answer; the reader only trusts a recorded value whose watcher scope matches the
  question being read. On the Python side `forms.select_is_answered()` (option
  value **and** selected text) drives the fill step's "already answered" check,
  the form enumeration captures the select's `selected_text`, and
  `forms.is_prompt_answer()` keeps a prompt out of the store even if some future
  layout slips past the reader. The two corrupt entries and the leaked
  government-employment answer were removed from `data/answers.json`. The 668-line
  `linkedin_ask_human.py` was split into the `linkedin_ask_human/` package
  (`answer_js`, `banner_js`, `flow`, `store`) under the 415-line rule, with the
  same public API re-exported.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_ask_human/answer_js.py` (`isSelectPrompt`,
  scope check), `src/tools/linkedin_ask_human/store.py` (`is_prompt_answer`
  guards), `src/tools/forms.py` (`select_is_answered`, `is_prompt_answer`),
  `src/tools/linkedin_easy_apply_fill/field_filling.py`
  (`_control_already_answered`),
  `src/tools/linkedin_easy_apply_fill/form_queries/scripts.py` (`selected_text`);
  `tests/unit/test_task5_form_answers.py` (9 tests). Live check against the real
  LinkedIn Easy Apply form over CDP (the real "right to work" `<select>` cloned
  into the page; nothing clicked in the real form, nothing submitted): opening the
  dropdown and clicking away both read `{"value": "", "done": false}`, picking
  "Full working rights - Citizenship or Permanent resident" read it back, and
  reading another question's markers returned `{"value": "", "done": false}` (no
  leak) — all PASS (uncommitted).

### BUG-082 — a radio option's aria-label (the question) was saved as the answer

- **Symptom:** `data/answers.json` stored the question text as the human's
  answer for several Yes/No screening questions, e.g.
  `"are you happy coming to the office 2-3 days per week": "Are you happy coming
  to the office 2-3 days per week?"`. The Task 5 banner also listed
  `One of: <question>, <question>` instead of `Yes, No`.
- **Root cause:** LinkedIn's 2026 SDUI radio layout is a native
  `input[type=radio]` whose associated `label[for]` is empty and whose
  `aria-label` is the **question**; the visible option text ("Yes"/"No") is in a
  sibling `<p>` of the next ancestor. The form enumeration's option reader and
  Task 5's answer watcher/reader fell back to `aria-label`, so the option label
  became the question. Clicking "Yes" then stored the question text.
- **Fix:** added `src/tools/choice_option_text.py` with `_autojobOptionText`,
  which resolves the visible option text from the associated label, the option
  row (only while it contains this single choice), or a sibling text block, and
  never falls back to `aria-label`. It is shared by the enumeration, Task 5's
  watcher/reader, and the checkbox-group scripts. The watcher also resolves a
  click on the option text to that row's input and accepts a click inside the
  marked option row. `answers.answer_echoes_question()` plus guards in
  `save_answer`, `_store_answer`, `_remember_answer`, and the Task 5 wait keep a
  question echo out of the store. The question-echo entries in
  `data/answers.json` were removed; the three selections visible on the live form
  were repaired to `Yes`, and the ambiguous police-check entry was removed so the
  question is asked again rather than guessed.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/choice_option_text.py`,
  `src/tools/answers.py` (`answer_echoes_question`, `save_answer` guard),
  `src/tools/linkedin_ask_human/answer_js.py`,
  `src/tools/linkedin_ask_human/store.py`,
  `src/tools/linkedin_ask_human/flow.py`,
  `src/tools/linkedin_easy_apply_fill/form_queries/scripts.py`,
  `src/tools/linkedin_easy_apply_fill/checkbox_groups.py`;
  `tests/unit/test_task5_form_answers.py` (echo + store guards),
  `tests/integration/test_choice_option_text_live.py` (4 live browser tests).
  Live read-only check against the open CORTO Easy Apply form over CDP (nothing
  clicked, nothing submitted): enumeration returned `"option": "Yes"`/`"No"` for
  all four radio groups, and the reader returned `{"value":"Yes","done":true}`
  for the three selected groups and `{"value":"","done":false}` for the
  unanswered AWS group. Existing role-radio, native-radio, and SDUI checkbox live
  tests also pass. (uncommitted)


### Task 26 follow-up — BUG-122

Completion gating supersedes the former early-save/settle behavior. See
[BUG-122](task_26_bugs.md) for the root cause, fix, and real LinkedIn evidence.
Prompt and question-echo guards from BUG-037/BUG-082 remain covered.
