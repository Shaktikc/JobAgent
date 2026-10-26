# Self-Healing Loop — Bugs (auto-recorded)

Bugs captured by the bounded Easy Apply self-healing loop (Task 11). Each entry is
written **before** recovery starts, with a link to the failure bundle under
`data/debug/self_healing/` (screenshot, DOM excerpt, page text, browser console,
and structured evidence).

See [`bug_log.md`](bug_log.md) for the master index, status markers, and the shared
entry format. A repeated failure fingerprint updates the existing entry's
occurrence count instead of creating a duplicate.

Implementation bugs found while building the loop are recorded here too, so the
same index covers runtime crashes and the recovery machinery itself.

| ID | Symptom (short) | Status | Fix commit(s) |
|----|-----------------|--------|---------------|
| BUG-043 | state ↔ tools import cycle broke graph tests | 🟢 Fixed | (uncommitted) |
| BUG-044 | repeated fingerprint crashed on Windows backslash paths | 🟢 Fixed | (uncommitted) |
| BUG-045 | bug index update overwrote symptom/status columns | 🟢 Fixed | (uncommitted) |
| BUG-046 | same-job reopen ignored non-HTTP job URLs | 🟢 Fixed | (uncommitted) |
| BUG-047 | failed reopen left the new browser alive | 🟢 Fixed | (uncommitted) |
| BUG-048 | status overlay swallowed the Easy Apply Next click | 🟢 Fixed | (uncommitted) |
| BUG-049 | failure screenshot captured the active tab, not the failing page | 🟢 Fixed | (uncommitted) |
| BUG-050 | stuck walk with a listed resume never triggered self-healing | 🟢 Fixed | (uncommitted) |
| BUG-051 | form did not advance on a contact step (modal closed mid-walk) | 🔴 Open | (pending) |
| BUG-052 | SDUI required question read as optional → walk stopped as "form did not advance" | 🟢 Fixed | (uncommitted) |

---

### BUG-043 — importing the graph failed with a state ↔ tools cycle

- **Symptom:** collecting `tests/unit/test_graph.py` raised
  `ImportError: cannot import name 'JobDescription' from partially initialized
  module 'src.state'` after `state.py` imported `SelfHealingOutcome`.
- **Root cause:** `src/tools/__init__.py` eagerly imported
  `linkedin_best_matching_resume`, which imports `src.state`; `state.py` then
  imported the Task 11 model, closing the cycle.
- **Fix:** re-export the resume helpers lazily from `src/tools/__init__.py`, the
  same pattern `src/tools/browser.py` already uses for moved modules.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/__init__.py`, `src/state.py`,
  `src/tools/self_healing/models.py`; full unit suite; commit `(uncommitted)`.

### BUG-044 — repeated failure fingerprint crashed on Windows paths

- **Symptom:** recording the same failure twice raised
  `re.error: bad escape \U at position 64` while updating `Occurrences`.
- **Root cause:** `re.sub(..., line, ...)` treated the Windows bundle path in the
  replacement string as regex escape sequences.
- **Fix:** use `lambda _match: line` as the replacement so path text is literal.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/self_healing/buglog.py`;
  `test_buglog_deduplicates_and_updates_the_index`; commit `(uncommitted)`.

### BUG-045 — bug index update overwrote the symptom/status columns

- **Symptom:** inserting a `BUG-NNN` row shifted the status into the symptom
  column and the fix into the status column.
- **Root cause:** the split row's leading empty cell was not accounted for, so
  indices 3/4 were one column too early.
- **Fix:** update status at index 4 and fix at index 5; keep the insertion
  separated by blank lines.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/self_healing/buglog.py`;
  `test_buglog_deduplicates_and_updates_the_index`; commit `(uncommitted)`.

### BUG-046 — same-job reopen ignored a non-HTTP job URL

- **Symptom:** the live recovery test fell back to searching the results list and
  reported "the details pane still shows …" instead of opening the recorded job.
- **Root cause:** `_open_target` only accepted URLs starting with `http`; local
  `file:` fixtures (and any other supported scheme) were skipped.
- **Fix:** accept `http://`, `https://`, and `file:` URLs; the card/title search
  remains the fallback.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/self_healing/recovery.py`;
  `test_reopen_same_job_opens_the_recorded_url`; commit `(uncommitted)`.

### BUG-047 — a failed reopen left the new browser holding the profile

- **Symptom:** after a failed same-job reopen, the next recovery attempt could hit
  "another browser is already using the AutoJobApply profile".
- **Root cause:** the failure paths called `close_run`, which only detaches the
  CDP handle and leaves Chromium open.
- **Fix:** use `close_run_force` on both reopen failure and exception paths.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/self_healing/recovery.py`; live self-healing test;
  commit `(uncommitted)`.

### BUG-048 — one swallowed Next click made the walk stop as "form did not advance"

- **Symptom:** the contact step (`1/3 pages`) had an enabled **Next** button and all
  visible fields filled, but the walk stayed on the same step and stopped with
  `no resume control found on this form step; form did not advance to a new step`.
- **Root cause:** the walk advanced with exactly one click. If that click was
  swallowed (a transient overlay, a stale handle, or LinkedIn's saving layer), the
  form stayed on the same step and the walk treated it as permanently stuck. The
  missing-resume note was incidental: the resume step comes later. The original
  screenshot could not prove the exact click blocker (it captured the wrong tab,
  BUG-049), and the same job now advances on a live re-run.
- **Fix:** re-resolve the current step's **Next** button and retry it **once** with a
  fresh handle before declaring the form stuck. Also mark the read-only Task 9 status
  panel `pointer-events:none` (a live probe proves a top-layer panel can block a
  click), and classify a stuck step ahead of the soft "no resume control" note.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_easy_apply_fill/form_walk.py`; unit
  `test_task4_retries_a_swallowed_next_click_once`; `src/tools/linkedin_status_overlay.py`;
  unit `test_panel_never_intercepts_clicks`; live
  `test_status_panel_does_not_swallow_the_next_click`; same job re-run advanced to
  3/3 pages; original bundle
  `data/debug/self_healing/20261025-220753-518929-6905d56d8351`; live probe:
  a panel without the CSS blocked the click (0), with `pointer-events:none` the
  click landed (1); commit `(uncommitted)`.
- **Failure fingerprint:** `6905d56d8351d55edfc4`
- **Occurrences:** 1 (first 2026-10-25T22:07:54+00:00)

### BUG-049 — failure screenshot captured the active tab, not the failing page

- **Symptom:** the BUG-048 bundle's `screenshot.png` showed a black LinkedIn loading
  screen while `dom.html` and `failure.json` showed the contact form, so the screenshot
  was misleading during diagnosis.
- **Root cause:** `capture_failure` used `session.take_screenshot`, which captures the
  browser's currently active page/tab; the run page is not guaranteed to be active.
- **Fix:** capture `run.page.screenshot()` (base64) for the exact failing page, with
  `session.take_screenshot` only as a fallback.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/self_healing/capture.py`; live two-page probe (failing
  page screenshot mean 253/255, active black tab via the old session call 3.8/255);
  BUG-048 bundle comparison; commit `(uncommitted)`.

### BUG-050 — a stuck walk with an already-listed resume never triggered self-healing

- **Symptom:** a live run stopped with
  `fill: no resume control found on this form step; form did not advance to a new
  step; stopping before Submit`, yet **no** `self-heal:` line appeared: the browser
  was left open and `verify` failed with "acceptance criteria not met".
- **Root cause:** the fill node's `_fill_errors` ignored whether the walk actually
  reached the terminal step. When the form's resume was already listed
  (`resume_attached=True`) and every required field was filled, a crashed walk looked
  like a successful fill, so `errors` was empty and `heal_fill_failure` was never
  called. The loop's own `fill_failure_reason` knew the walk had stopped, but the
  node did not use it - the two success rules had diverged.
- **Fix:** Automatic runtime recovery: the failed browser session was closed, the same job was reopened, and the fill succeeded without a source change.
  `reached_terminal_step`; the fill node now delegates `_fill_errors` to it, and
  `verify._task4_succeeded` / `_task4_ok` require the terminal step too. A stopped
  walk is now `form_did_not_advance` and triggers the loop.
- **Status:** 🟢 Fixed
- **Evidence:** `src/nodes/fill.py`, `src/tools/self_healing/fingerprint.py`,
  `src/nodes/verify.py`, `src/tools/linkedin_easy_apply_fill/form_walk.py`; unit
  `test_a_stuck_step_outranks_the_missing_resume_note` (attached resume still
  errors) and the full unit suite; commit `(uncommitted)`.
- **Recovery evidence:** bundle `C:\Users\shakt\AppData\Local\Temp\bug050-yaymulie\b`; attempts=1; run=`run-2`

### BUG-051 — form did not advance to a new step: no resume control found on this form step; form did not advance to a new step; stopping before submit

- **Symptom:** fill: form did not advance to a new step
- **Root cause:** Auto-classified as `form_did_not_advance` during `fill`; see the bundle for the failing step/DOM. A source-level root cause is still pending.
- **Fix:** Pending. Recorded before any repair attempt.
- **Status:** 🔴 Open
- **Evidence:** bundle `C:\Users\shakt\OneDrive\Desktop\project\AutoJobApply\data\debug\self_healing\20261026-075609-194086-db6a12a862ca`; captured 2026-10-26T07:56:09.355521+00:00
- **Failure fingerprint:** `db6a12a862ca6b3775dc`
- **Occurrences:** 1 (first 2026-10-26T07:56:09+00:00)

### BUG-052 — a required SDUI question was read as optional, so the walk stopped as "form did not advance"

- **Symptom:** on the resume step (`2/4 pages`) of a Workable Easy Apply form the
  walk stopped with `fill: no resume control found on this form step; form did not
  advance to a new step; stopping before Submit`. The resume was already listed and
  selected; the real blocker was the required screening question **"Are you eligible
  to work in this country?*"** left unanswered. The loop still classified it as a
  recoverable `form_did_not_advance` and would retry the same job in a fresh browser.
- **Root cause:** `_ENUMERATE_FORM_QUERY` detected `required` only from a
  `required`/`aria-required` attribute. LinkedIn's newer SDUI Easy Apply carries
  neither: it marks a required question with a trailing `*` in the label
  (`<p>Are you eligible to work in this country?*</p>`) and an `error-message-<id>`
  described-by id on the question's `fieldset` (an optional control points at an
  `<id>-info` id instead). The eligibility radio group — and the required resume
  radio group — were therefore read as `required=false`, so the walk could not name
  the blocker and `classify_failure`/`fill_failure_reason` fell back to the generic
  "form did not advance" (recoverable) instead of `required_question_unanswered`.
- **Fix:** read the SDUI required marker in the enumeration query via a new injected
  helper `REQUIRED_MARKER_JS` (in `checkbox_groups.py`): a control/group whose
  described-by id starts with `error-message-`, and/or a trailing `*` in the group's
  own question label (one hop up from the fieldset, choices only, so an unrelated
  `*` in a shared ancestor is never picked up). Also make a required, unanswerable
  question outrank the soft walk note in `classify_failure` and
  `fill_failure_reason`, so the run names the question and the loop does **not**
  waste its attempts reopening a form it cannot answer (it flows to Task 5/the human).
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_easy_apply_fill/checkbox_groups.py`
  (`REQUIRED_MARKER_JS`, injected by `_with_apply_root`),
  `src/tools/linkedin_easy_apply_fill/form_queries/scripts.py` (uses `requiredOf`),
  `src/tools/self_healing/fingerprint.py` (`classify_failure`,
  `fill_failure_reason`); unit
  `test_a_stuck_step_with_a_required_unknown_question_is_not_retried`; live
  `test_task4_reads_the_sdru_required_marker` (real Chromium: the SDUI group reads
  `required=True`, the optional textarea stays optional) plus a live walk probe that
  stopped with `required questions are unanswered: Eligible to work?` and classified
  `required_question_unanswered` (not recoverable); full unit suite + live Task 4
  fill suite (11/11) + live self-healing suite (4/4); commit `(uncommitted)`.
- **Failure fingerprint:** `bd4ac7ea2b35e7fa8437`
- **Occurrences:** 1 (first 2026-10-26T08:02:18+00:00)

### BUG-053 — required field was not filled: no resume control found on this form step; reached the last step (only submit remains)

- **Symptom:** fill: required fields were not filled: Experience on Agile & Scrum ?
- **Root cause:** Auto-classified as `required_field_not_filled` during `fill`; see the bundle for the failing step/DOM. A source-level root cause is still pending.
- **Fix:** Pending. Recorded before any repair attempt.
- **Status:** 🔴 Open
- **Evidence:** bundle `C:\Users\shakt\OneDrive\Desktop\project\AutoJobApply\data\debug\self_healing\20261026-083840-711732-e6e2e833d523`; captured 2026-10-26T08:38:40.889239+00:00
- **Failure fingerprint:** `e6e2e833d523024d8224`
- **Occurrences:** 1 (first 2026-10-26T08:38:40+00:00)
