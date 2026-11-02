# Task 21 — Skip every Easy Apply question without an asterisk

| ID | Symptom | Status | Fix commit(s) |
|----|---------|--------|---------------|
| BUG-094 | Voluntary/unstarred questions were answered or shown to the human | 🟢 Fixed | Uncommitted; base `d732dc4` |
| BUG-095 | Visible group headings lost their asterisks or borrowed another question's label | 🟢 Fixed | Uncommitted; base `d732dc4` |
| BUG-096 | Starred salary, experience and notice questions were read as character counters and skipped | 🟢 Fixed | Uncommitted; base `d732dc4` |

### BUG-094 — metadata bypassed the no-asterisk skip rule

- **Symptom:** TikTok's Additional Questions step (3/4) asked about unstarred
  gender identity, disability and ethnicity. Remembered answers and existing
  optional selections could also reach answering/persistence.
- **Root cause:** the live LinkedIn DOM uses `aria-describedby="error-message-…"`
  on voluntary fieldsets. `REQUIRED_MARKER_JS` treated that as required;
  `is_required_field` accepted that flag, and name-based propagation could keep
  an unstarred question sharing a choice name with a starred question.
- **Fix:** resolve requiredness only from each question's own visible label.
  Filter before grouping, LLM/store selection, checkbox persistence and human
  prompts. Normalize retained copies for downstream required-field accounting.
  Metadata-only flags cannot override the absence of a visible `*`.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/forms.py`,
  `src/tools/linkedin_easy_apply_fill/required_only.py`,
  `tests/unit/test_task21_optional_questions.py`,
  `tests/integration/test_task21_optional_walk_live.py`.
  Live `scripts/verify_task21_linkedin.py` on 2026-11-02: 33 optional controls
  across three questions stayed unchanged; no optional chooser calls, unknown
  records, prompts or answer-store writes. Local evidence:
  `data/debug/task21/skip-check.json` and `skip-check.png`.
  Uncommitted working-tree fix; base commit `d732dc4` (no commit authorized).

### BUG-095 — accessible text hid or contaminated the visible group label

- **Symptom:** the live TikTok work-rights question visibly ends in `*`, but
  enumeration returned the question without it. Broad section queries and
  fallback option labels could also give an optional question a nearby `*`.
- **Root cause:** group discovery preferred `aria-label` over the actual heading
  and searched shared containers/options for markers. A control's aria text
  need not contain the visible heading's marker.
- **Fix:** new `question_labels.py` resolves visible associated labels, legends,
  labelled-by nodes and local SDUI headings before answering. It excludes hidden
  text, metadata-only labels, option markers and other questions' controls.
  Self-healing reloads the helper and filter before dependent query/fill modules.
- **Status:** 🟢 Fixed — label discovery is verified; Task 21's final real-site
  navigation check still awaits the human's starred work-rights answer.
- **Evidence:** live before/after DOM discovery in
  `data/debug/task21/before-dom.json` and `discovery-after.json`;
  `tests/integration/test_task21_required_labels_live.py`;
  `src/tools/linkedin_easy_apply_fill/question_labels.py`;
  `src/tools/linkedin_easy_apply_fill/form_queries/scripts.py`;
  `src/tools/self_healing/recovery/repair.py`.
  All 38 combined browser regressions pass, including Task 20 validation,
  classic/SDUI label discovery, optional-only navigation and required human input.
  Uncommitted working-tree change; base commit `d732dc4`.

### BUG-096 — nested character counters hid starred text questions

- **Symptom:** job `4485457082` left **What's your expected annual base salary?***,
  software-engineering experience and notice-period questions blank despite their
  visible asterisks. Screenshot: `Screenshot 2026-11-02 181643.png`.
- **Root cause:** SDUI places the question's `<p>` above a wrapper containing the
  input and trailing helper text. The local-label fallback found the helper's
  `0/20 0 of 20 characters` paragraph first, returned it as the question, and the
  required-only filter correctly dropped that unstarred but incorrect label.
- **Fix:** only accept local label candidates that precede their control in DOM
  order. Continue to the enclosing question wrapper when inner paragraphs are
  trailing counters/help text. Keep the per-question visible-asterisk policy.
- **Status:** 🟢 Fixed — required-label discovery and the production human-answer
  prompt were verified on the reported LinkedIn job; browser regressions pass.
- **Evidence:** `src/tools/linkedin_easy_apply_fill/question_labels.py`;
  `tests/integration/test_task21_required_text_fields_live.py` reproduces the
  failure before the fix (2 failed) and passes after it with the existing label
  regressions (10 passed). Tests exercise text inputs, textareas and selects,
  optional-field preservation, and markup with/without helper test IDs. The final
  five regressions cover both automatic answering and human-answer fallback, plus
  trailing helper asterisks that must not require optional/unlabelled controls.
  Broader browser checks: 35 passed, plus 8 existing label checks passed in the
  initial focused run. Default suite: 719 passed, 82 skipped, one pre-existing
  `.opencode` skill-path failure. Focused lint, compilation and wheel build pass.
  Real job `4485457082`: production navigation reached Additional Questions;
  all 7 starred questions (11 controls) reached the chooser. The salary question
  displayed the actual Task 5 banner and remained required/unknown when the
  deliberately unknown chooser received no human answer; no answer was invented.
  Evidence: `data/debug/task21/reported-walk-unknown.json`,
  `reported-label-comparison.json`, `reported-salary-prompt.json` and
  `reported-salary-prompt.png`. No application was submitted.
  Uncommitted working-tree fix; base commit `d732dc4` (no commit authorized).
