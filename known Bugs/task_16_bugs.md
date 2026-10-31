# Task 16 — Bugs (strict resume gate, skip unmatched jobs)

Bugs whose root cause is in **Task 16**: applying only when an existing resume is a
strong match, closing the skipped Easy Apply form, and moving to the next job
without reopening the skipped one.

See [`bug_log.md`](bug_log.md) for the master index and the entry format.
Status: 🟢 Fixed · 🟡 Fixed (superseded) · 🔴 Open · ⚪ Won't fix

| ID | Symptom (short) | Status | Fix commit(s) |
|----|-----------------|--------|---------------|
| BUG-073 | a hidden (`display:none`) Easy Apply modal still read as open, so a closed skip looked stuck | 🟢 Fixed | `29c0aff` |
| BUG-074 | a skipped card gained " (Verified job)" and was reopened as a "new" job | 🟢 Fixed | `29c0aff` |
| BUG-076 | skip identity used the description title, so cards with longer titles were reopened and the loop alternated | 🟢 Fixed | `121bffb` |

Related Task 3.2 fix consumed by this gate: **BUG-078/BUG-079** in
[`task_3_bugs.md`](task_3_bugs.md) — per-candidate ratings and richer resume
profiles. The strict gate now uses the LLM's strong rating from that reply.

---

### BUG-073 — a hidden Easy Apply modal was treated as an open form

- **Symptom:** after Task 16 skipped a job and clicked the Easy Apply modal's
  **Dismiss** control (the modal was hidden with `display:none`), the live
  `close_easy_apply_form` check still reported the form open and returned
  `False`. `open_next_job` would then stop with
  `"the Easy Apply form could not be closed"` instead of opening the next
  unskipped job. Reproduced in a real Chromium window by
  `tests/integration/test_task16_skip_live.py`.
- **Root cause:** `FIND_APPLY_ROOT_JS` filtered out invisible dialog candidates
  but then fell back to the hidden `.jobs-easy-apply-modal` element
  (`const dialog = applyish || formish || visible[0] || easy || null`). A modal
  left in the DOM after it was closed therefore kept counting as an open
  application form.
- **Fix:** `findApplyRoot()` no longer returns the hidden Easy Apply modal
  fallback; only a visible dialog (or a visible inline form) counts as open.
  `read_apply_modal` and every caller (Tasks 2, 4, 8) now agree that a hidden
  modal is closed.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/browser.py` (`FIND_APPLY_ROOT_JS`),
  `src/tools/linkedin_resume_gate.py` (`close_easy_apply_form`),
  `tests/integration/test_task16_skip_live.py`
  (`test_dismiss_closes_the_form_and_never_submits`,
  `test_discard_confirmation_closes_the_draft_without_submitting`). Commit
  `29c0aff`.

---

### BUG-074 — a skipped job was reopened when its card title gained " (Verified job)"

- **Symptom:** in a live LinkedIn run with only a pastry-chef resume in the pool,
  Task 16 skipped `Senior Engineer ( .Net/Data migration / ETL)`, closed the form,
  and opened the next card. The next card's title was the **same job** re-rendered
  as `Senior Engineer ( .Net/Data migration / ETL) (Verified job)`. Its skip key
  did not match, so the same posting was opened and skipped again; only the
  skipped-jobs cap stopped the loop (two identical `task16` records).
- **Root cause:** `_job_key` normalized only case/whitespace. LinkedIn appends a
  **" (Verified job)"** status badge to a card's title line after it is opened, so
  the same posting produced two different keys. The Task 8 submit probe already
  stripped this suffix; the card/skip identity did not.
- **Fix:** `_job_key` strips a trailing `(Verified job)` (case-insensitive) before
  building the tried/skip key, mirroring the submit probe. Legitimate
  parenthesised title text is preserved.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_job_selection.py` (`_job_key`,
  `_TITLE_STATUS_SUFFIX`), `tests/unit/test_linkedin_apply_loop.py`
  (`test_job_key_ignores_the_verified_job_status_suffix`), and the live run log
  that reproduced the reopen (temp pastry-only resume pool, two skips). Commit
  `29c0aff`.

---

### BUG-076 — skipped jobs were reopened because the skip key used the description title

- **Symptom:** a live strict-mode run skipped
  `Engineering Team Lead | .NET + React (Verified job)`, then
  `ServiceNow Developer | Perm (Verified job)`, then reopened
  `Engineering Team Lead | .NET + React (Verified job)` and `ServiceNow` again.
  The results list appeared to jump around instead of moving down the list. After
  several repeats the browser's CDP WebSocket closed unexpectedly.
- **Root cause:** `match` stored `skipped_titles` from the **description** heading
  (`Engineering Team Lead`), while Task 2's results card is keyed by its longer
  **card** title (`Engineering Team Lead | .NET + React (Verified job)`).
  `_job_key` therefore produced different keys, so after the next skip the earlier
  card became eligible again. The two jobs alternated, multiplying LLM/browser
  work until the connection was lost.
- **Fix:** `match` now records the exact `task2.job_title` (the card identity) in
  `skipped_titles`, plus the description title as a fallback. `_job_key` still
  strips the trailing `(Verified job)` badge, and `open_next_job` excludes every
  accumulated skip key. Selection continues from the top of the list, skipping
  Applied and previously skipped cards, so it moves forward instead of revisiting.
- **Status:** 🟢 Fixed
- **Evidence:** `src/nodes/match.py`, `src/tools/linkedin_job_card.py`
  (`_job_key`), `tests/unit/test_graph.py`
  (`test_match_records_the_card_title_for_skip_identity`), and a live run with
  five skips that advanced through unique cards in order (4 → 5 → 7 → 8 → 9,
  including `PL/SQL Developer (Verified job)` and
  `Engineering Team Lead | .NET + React`), with no reopened job.
