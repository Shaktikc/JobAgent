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
