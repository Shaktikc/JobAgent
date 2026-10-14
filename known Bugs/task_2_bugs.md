# Task 2 — Bugs (select a job, open its Easy Apply form)

Bugs whose root cause is in **Task 2**: reading the results list, opening the
first Easy Apply job, and finding/clicking the correct **Easy Apply** button.
BUG-019 also affects the Task 8 loop, but the defect lives in Task 2's list
handling.

See [`bug_log.md`](bug_log.md) for the master index and the entry format.
Status: 🟢 Fixed · 🟡 Fixed (superseded) · 🔴 Open · ⚪ Won't fix

| ID | Symptom (short) | Status | Fix commit(s) |
|----|-----------------|--------|---------------|
| BUG-017 | AI/semantic job cards were `div[role=button]`, not found | 🟢 Fixed | `6d369f7` |
| BUG-018 | fallback scan picked a job **card** as the apply button | 🟢 Fixed | `9ad31a9` |
| BUG-019 | stale card handles after a click → jobs silently skipped | 🟢 Fixed | `84b0bb5` |

---

### BUG-017 — AI/semantic job cards were invisible to the classic selectors

- **Symptom:** on the AI/semantic results page the run stalled waiting for job
  cards that the classic `<li>` selectors could not see.
- **Root cause:** that page renders job cards as `div[role=button]`, not classic
  `<li>` items.
- **Fix:** `_AI_JOB_CARDS_JS` scans `div[role=button]` controls and tags job-like
  ones with `data-autojob-card`; `results_count` and `read_job_cards` then find
  them.
- **Evidence:** `src/tools/browser.py` (`_mark_ai_job_cards`);
  `test_read_job_cards_finds_ai_job_cards`. Commit `6d369f7`.

### BUG-018 — the fallback scan picked a job **card** as the apply button

- **Symptom:** the agent clicked a job card instead of the blue **Easy Apply**
  button.
- **Root cause:** a job card's accessible text also contains "Easy Apply", so the
  label-only fallback scan chose the first card.
- **Fix:** `looks_like_job_card_label` (location/status markers) plus
  `_element_is_job_card`; the fallback excludes cards and returns the real button.
- **Evidence:** `src/tools/browser.py`, `src/tools/linkedin.py`;
  `test_find_job_apply_button_fallback_skips_job_cards`. Commit `9ad31a9`.

### BUG-019 — stale card handles after a click silently skipped jobs

- **Symptom:** after opening a job, later jobs were skipped.
- **Root cause:** on the semantic results page, clicking a card navigates and
  re-renders the list, detaching every previously resolved card element. Reusing
  stale handles clicked nothing and left the details pane on the first job. (The
  Task 8 `open_next_job` loop reused the same list.)
- **Fix:** re-read the results list on every attempt to get fresh handles, track
  tried/applied jobs by a stable job key, and cap attempts (`_MAX_JOB_ATTEMPTS`).
- **Evidence:** `src/tools/linkedin_job_selection.py` (`read_job_cards`,
  `_job_key`, `_task2_on_page`). Commit `84b0bb5`.
