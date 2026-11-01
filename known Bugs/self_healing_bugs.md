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
| BUG-053 | a human-answered radio lost its marker → "required field was not filled" | 🟢 Fixed | (uncommitted) |
| BUG-055 | a human-answered radio lost its marker → "required field was not filled" | 🟢 Fixed | (uncommitted) |
| BUG-056 | SDUI `<dialog>`/typeahead race → false step advance, no resume attached | 🟢 Fixed | (uncommitted) |
| BUG-057 | an LLM-answered radio lost its marker → "required field was not filled" | 🟢 Fixed | (uncommitted) |

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
- **Evidence:** `src/tools/self_healing/recovery/reopen.py`;
  `test_reopen_same_job_opens_the_recorded_url`; commit `(uncommitted)`.

### BUG-047 — a failed reopen left the new browser holding the profile

- **Symptom:** after a failed same-job reopen, the next recovery attempt could hit
  "another browser is already using the AutoJobApply profile".
- **Root cause:** the failure paths called `close_run`, which only detaches the
  CDP handle and leaves Chromium open.
- **Fix:** use `close_run_force` on both reopen failure and exception paths.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/self_healing/recovery/reopen.py`; live self-healing test;
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
  `test_task4_retries_a_swallowed_next_click_once`; `src/tools/linkedin_status_overlay/panel_js.py`;
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
- **Related:** this bundle also shows the BUG-055 stale-marker defect (the optional
  "Do you have experience using Databricks?" radio the human answered was recorded
  `filled=false, error="field element not found"`); that part is fixed by BUG-055.
  The "form did not advance" stop itself (the footer buttons read as `[]`) is a
  separate issue and stays 🔴 Open.

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

### BUG-053 — a human-answered radio lost its marker → "required field was not filled"

- **Symptom:** on a Synechron Easy Apply form (`4/4 pages · Review your
  application`) the required radio **"Experience on Agile & Scrum ?"** was recorded
  `known=true, filled=false, error="field element not found"`, so the fill node
  reported `required fields were not filled`, even though the review page
  (`page.txt`) showed it answered **Yes**.
- **Root cause:** same stale-marker defect as BUG-055. The enumeration marks a
  choice control by putting `data-autojob-fill` on its clickable label; when the
  human answers the radio on the real control in Task 5, React re-renders the marked
  wrapper away, so the cached marker no longer resolves. `_apply` then recorded
  `field element not found` although `ask_human_for_answer` had just read the
  human's answer from that same (already-set) control.
- **Fix:** fixed by BUG-055's change in `field_filling._apply` — a field whose cached
  marker is gone but whose answer came from the human (`source == "human"`) is
  recorded as filled, because the human set the control directly.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_easy_apply_fill/field_filling.py`; unit
  `test_task4_human_answered_radio_survives_a_stale_marker`; bundle
  `C:\Users\shakt\OneDrive\Desktop\project\AutoJobApply\data\debug\self_healing\20261026-083840-711732-e6e2e833d523`;
  captured 2026-10-26T08:38:40.889239+00:00; commit `(uncommitted)`.
- **Failure fingerprint:** `e6e2e833d523024d8224`
- **Occurrences:** 1 (first 2026-10-26T08:38:40+00:00)

### BUG-055 — a human-answered radio lost its marker → "required field was not filled"

- **Symptom:** on the Additional Questions step of a Galileo Search Easy Apply form
  (`4/4 pages · Review your application`) two required radios the human had answered
  in Task 5 — **"Have you delivered an AI solution into production inside a medium or
  large organisation?"** and **"Are you available for a full-time contract?"** — were
  recorded `known=true, filled=false, error="field element not found"`. The fill node
  reported `required fields were not filled: …` and the self-healing loop reopened
  the same job. The review page (`page.txt`/`dom.html`) showed both answered **Yes**,
  so the answers were already on the form.
- **Root cause:** the enumeration marks a choice control by putting
  `data-autojob-fill` on its clickable label (`clickTarget`). When the human answers
  the question on the real control in Task 5, React re-renders the marked wrapper
  away, so the cached marker no longer resolves. `_apply` then found no element and
  recorded `field element not found`, even though `ask_human_for_answer` had read
  the human's answer from that same (already-set) control. The checkbox path already
  handles this by reading the group's live selection and never toggling what the
  form holds; the radio path did not.
- **Fix:** in `_apply`
  (`src/tools/linkedin_easy_apply_fill/field_filling.py`), when the cached marker is
  gone but the answer came from the human (`source == "human"`), record the field as
  filled instead of `field element not found`: the human set the control directly, so
  the answer is already on the form.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_easy_apply_fill/field_filling.py`; unit
  `test_task4_human_answered_radio_survives_a_stale_marker` (fails before the fix
  with `filled_fields == 0`, passes after); full unit suite; bundle
  `C:\Users\shakt\OneDrive\Desktop\project\AutoJobApply\data\debug\self_healing\20261026-085927-832116-15ba2f68132a`;
  captured 2026-10-26T08:59:27.987350+00:00; commit `(uncommitted)`.
- **Failure fingerprint:** `15ba2f68132a6373f438`
- **Occurrences:** 1 (first 2026-10-26T08:59:28+00:00)

### BUG-056 — no resume control on the form step: no resume control found on this form step

- **Symptom:** on the BizCover Easy Apply form (`1/6 pages`, Contact info) the
  walk ended with `fill: resume was not attached` and only the note
  `no resume control found on this form step`, although the form had six steps
  and the resume lives on a later one.
- **Root cause:** three linked defects in the new SDUI Easy Apply layout
  (a native `<dialog>`, hashed classes):
  1. `findApplyRoot()` did not recognise the `<dialog>` and could return either
     the `Apply to <company>` **heading** (before the controls rendered) or a
     page-level ancestor carrying an unrelated **Next**. `_task4_on_page` then
     read zero fields/navigation buttons, treated the empty shell as the terminal
     step, and returned without advancing or attaching the resume.
  2. The step identity hashed the modal's whole visible text, including the
     location typeahead's `[role="status"]` "N suggestions available" and
     suggestion list. Opening/closing the list changed the hash, so a Next click
     that did **not** advance looked like a new step; the walk looped on `1/6`
     until the step cap and ended silently.
  3. The city/location field is a typeahead (`role="combobox"`,
     `aria-autocomplete="list"`). Setting only its value left it uncommitted, so
     LinkedIn kept the form on Contact info (and toggled the suggestion list,
     producing the alternating hashes).
- **Fix:** in `FIND_APPLY_ROOT_JS`, return the visible `<dialog>` containing the
  `Apply to ...` heading directly, add `dialog[open]` to the candidates, and stop
  the inline ancestor climb before BODY/HTML. In `_task4_on_page`, wait for a
  just-rendered step to expose fields or a navigation/submit button before
  treating it as actionable, and name an exhausted step cap instead of ending
  silently. Add `STEP_IDENTITY_JS`, which hides transient status/listbox/option
  nodes before hashing the step, so typeahead churn cannot fake an advance. Add
  `TYPEAHEAD_COMMIT_JS`, which clicks the suggestion matching the filled value
  (and blurs the field) so Next accepts the city; blur the active control before
  every Next click. A shell that never renders is now `form_not_ready`
  (recoverable) instead of `resume_control_missing`.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/browser.py` (`FIND_APPLY_ROOT_JS`),
  `src/tools/forms.py` (`STEP_IDENTITY_JS`, `TYPEAHEAD_COMMIT_JS`),
  `src/tools/linkedin_easy_apply_fill/form_queries/scripts.py`,
  `src/tools/linkedin_easy_apply_fill/field_filling.py`,
  `src/tools/linkedin_easy_apply_fill/form_walk.py`,
  `src/tools/self_healing/fingerprint.py`; unit
  `test_task4_waits_for_a_modal_that_renders_before_its_fields`; live
  `test_task4_waits_for_a_sdui_dialog_to_render_its_fields` (heading-only
  `<dialog>` + page-level Next + uncommitted city typeahead) and
  `test_step_identity_ignores_transient_typeahead_text`; full unit suite; live
  Task 4 fill suite (13/13) and live self-healing suite (4/4).
  Live re-run of the same job: the walk advanced `1/6 → 5/6`, selected the listed
  resume `Shakti_KC_Resume_AgenticAI (1) (1).pdf`, and stopped on the genuinely
  unanswered required question "Share a spec, skill or multi-agent workflow…"
  (Task 5/human), not on a structural resume/advance failure. Bundle
  `C:\Users\shakt\OneDrive\Desktop\project\AutoJobApply\data\debug\self_healing\20261026-091205-718497-63d38a2eb8e7`;
  captured 2026-10-26T09:12:05.887682+00:00; commit `(uncommitted)`.
- **Failure fingerprint:** `63d38a2eb8e7a6448b9c`
- **Occurrences:** 1 (first 2026-10-26T09:12:05+00:00)

### BUG-057 — a required LLM-answered radio lost its marker → "required field was not filled"

- **Symptom:** on the Hays Easy Apply form (`4/4 pages · Review your application`) the
  required radio **"Have you implemented and integrated AI voice, conversational AI
  or chatbot platforms into production environments, incl integration with business
  systems such as CRM, contact centre, ERP or ecommerce?"** was recorded
  `known=true, filled=false, error="field element not found"` (the LLM had chosen the
  stored answer **Yes**). The fill node reported `required fields were not filled: …`
  and the self-healing loop classified it `required_field_not_filled` (recoverable).
  The review page (`page.txt`/`dom.html`) showed the question already answered **Yes**.
- **Root cause:** the same stale-marker class as BUG-053/BUG-055, but for an
  **LLM-answered** radio rather than a human-answered one. When the LLM chose the
  stored answer, the fill looked up the cached `data-autojob-fill` marker on the
  option label; the model round-trip gives React time to re-render the marked
  wrapper away, so `_marker_element` returned `None` and `_apply` recorded
  `field element not found` even though the group already held (or could still hold)
  the answer. BUG-055's fix only covered `source == "human"`, so the LLM path
  (`source == "llm"`) kept failing.
- **Fix:** Repair command completed and its tests passed; the same job was then reopened and filled.
  did not come from the human, re-resolve a **radio** group by its stable native
  `name` — the new `checkbox_groups.remark_radio_by_name` /
  `REMARK_RADIO_BY_NAME_JS` finds the option whose visible text matches the answer,
  re-marks it, and the normal click path fills it. A no-match still reports the
  original `field element not found`, so a genuinely missing control is unchanged.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_easy_apply_fill/checkbox_groups.py`
  (`REMARK_RADIO_BY_NAME_JS`, `remark_radio_by_name`),
  `src/tools/linkedin_easy_apply_fill/field_filling.py` (`_apply`); unit
  `test_fill_step_re_resolves_a_stale_radio_marker_by_name` (fails before the fix
  with `filled == 0`, passes after); live
  `test_task4_llm_answered_radio_survives_a_stale_marker_live` (real Chromium: the
  chooser re-renders the marked wrappers away, the fill re-resolves the group by
  `name`, clicks **Yes**, and reaches the terminal step; fails before the fix with
  `filled_fields == 0`); full unit suite; live Task 4 fill suite (14/14) and live
  self-healing suite (4/4); bundle
  `C:\Users\shakt\OneDrive\Desktop\project\AutoJobApply\data\debug\self_healing\20261026-095039-963174-e8dcc79d516c`;
  captured 2026-10-26T09:50:40.336477+00:00; commit `(uncommitted)`. The live
  verification used the exact LinkedIn role-radio markup in a local Chromium fixture
  (no LinkedIn login/network); the same-job live resume remains a human step.
- **Failure fingerprint:** `e8dcc79d516ca5e04c9a`
- **Occurrences:** 1 (first 2026-10-26T09:50:40+00:00)
- **Recovery evidence:** bundle `C:\Users\shakt\OneDrive\Desktop\project\AutoJobApply\data\debug\self_healing\20261026-095039-963174-e8dcc79d516c`; attempts=1; run=`bbb5df0f410e48738b9db1927a4b92dd`

### BUG-062 — form did not advance to a new step: no resume control found on this form step; form did not advance to a new step; stopping before submit

- **Symptom:** fill: form did not advance to a new step
- **Root cause:** Auto-classified as `form_did_not_advance` during `fill`; see the bundle for the failing step/DOM. A source-level root cause is still pending.
- **Fix:** Pending. Recorded before any repair attempt.
- **Status:** 🔴 Open
- **Evidence:** bundle `C:\Users\shakt\OneDrive\Desktop\project\AutoJobApply\data\debug\self_healing\20261027-060628-966030-99ae64bd9186`; captured 2026-10-27T06:06:29.344388+00:00
- **Failure fingerprint:** `99ae64bd91860b0b160f`
- **Occurrences:** 1 (first 2026-10-27T06:06:29+00:00)
- **Additional live evidence (2026-10-27, Task 12 verification):** a real
  `run_full_agent` fill on the LEAP Legal Software job reached the `3/4 pages`
  review step and then cycled through alternating step identities
  (`text:1998546265` → `text:193140353` → back to `text:1998546265`) while the
  footer kept reading `Review`; the walk filled 34 fields and stopped at the
  10-step cap without reaching the terminal step or submitting. This is the same
  open "form did not advance" family; the Task 12 context path was not the cause
  (the one job-specific question had an exact human-confirmed store answer).

### BUG-064 � a crash outside `fill` ended the run without self-healing

- **Symptom:** a live Task 8 run could crash/stop while opening the next job
  (or during the submit wait / browse / match) and no self-healing entry,
  browser close, repair, or resume happened. Only Task 4 fill failures entered
  the self-healing loop.
- **Root cause:** `heal_fill_failure` was wired into `src/nodes/fill.py` only.
  Every other node caught its own exception and returned `status="failed"`, so
  the uncaught-exception path that triggers capture/repair/reopen was never
  reached.
- **Fix:** new `src/nodes/self_heal_guard.py` wraps every graph node (except
  `cleanup`, which must never relaunch a browser). An uncaught crash now:
  captures evidence, records/updates a BUG entry, force-closes the failed run,
  runs the optional repair/test command, reopens the same job form or results
  page, and retries the **same node** up to `AUTOJOB_SELF_HEAL_MAX_ATTEMPTS`
  (default 3). `next_job`, `await_submit`, and `browse` no longer swallow their
  crashes, and the retried update carries the recovered `browser_run_id`,
  `task2`, and self-healing outcome back into graph state.
- **Status:** ?? Fixed
- **Evidence:** `src/nodes/self_heal_guard.py`, `src/graph.py`,
  `src/nodes/apply_loop.py`, `src/nodes/browse.py`;
  `tests/unit/test_self_heal_guard.py` (recovered retry, attempt cap, guard
  wrapping, and crash propagation). Full unit suite passes. Live Chromium check
  over a local HTTP page: capture → BUG-001 recorded → browser force-closed →
  fresh browser reopened the same page → `next_job` retried → recovered in one
  attempt. Uncommitted.

### BUG-065 — Task 1/2 self-healing could not close the failed browse browser

- **Symptom:** a returned Task 1–2 failure (`browse: job search returned no results`,
  no Easy Apply job, or form not opened) entered the new task guard, but the retry
  could not launch a fresh Chromium: the profile was still locked by the failed
  `browse` browser. The failure was also mis-filed as "unexpected exception while
  filling the form" even though no form was involved.
- **Root cause:** `browse` launches its own session via `start_tasks`, which only
  registers a run when Tasks 1–2 succeed; on failure it detaches and leaves the
  window open. With no `browser_run_id`, the guard's default close was a no-op, so
  the retry hit the profile lock. Separately, `classify_failure` had no browse-stage
  categories and fell through to the fill categories.
- **Fix:** `src/nodes/task_self_heal.py` adds the task-level guard and a
  `close_self_launched_browser` close hook (profile-wide close only when no run is
  registered, scoped `close_run_force` otherwise). `classify_failure` now takes a
  `stage` and emits `login_not_completed` / `search_no_results` /
  `search_filter_not_selected` / `easy_apply_job_missing`; the bug-log index scope
  follows the stage instead of always saying "fill".
- **Status:** 🟢 Fixed
- **Evidence:** `src/nodes/task_self_heal.py`,
  `src/tools/self_healing/fingerprint.py`, `src/tools/self_healing/buglog.py`,
  `src/tools/self_healing/capture.py`; `tests/unit/test_task_self_heal.py`
  (browse retry, login gate not retried, self-launched close, stage
  classification, browse-scoped bug index); full unit suite passes. Live Chromium
  check: a returned `search_no_results` stop was captured as
  `search_no_results`, the failed browse browser was force-closed (profile lock
  cleared), the task retried, and `browse` recovered on attempt 1. A separate live
  probe confirmed the profile-wide close lets the retry launch a fresh browser.
  Uncommitted.

### BUG-068 — results pagination could not advance: the results did not change after clicking next

- **Symptom:** after the human submitted `.Net Fullstack Engineer`, the Task 8
  loop returned to the results list, found every card on page 1 already Applied
  (`skipped 21 applied job(s)`), and stopped with
  `next_job: results pagination could not advance: the results did not change
  after clicking next; no unapplied Easy Apply job was opened`. The next-page
  control was present and correct (`Page 1/Page 2/Page 3/Next`), yet clicking it
  never moved the list, so the run recorded the stop as `unknown_exception`
  ("unexpected exception while filling the form") and retried by reopening page 1.
- **Root cause:** two defects:
  1. The current LinkedIn results page hashes its class names and renders the
     next-page control as a plain `<button>` (no `aria-label`) at the bottom of the
     page. `go_to_next_page` clicked it with a coordinate-based CDP mouse click
     (`Element.click()`); on the real page that click was swallowed (an overlapping
     sticky bar/ad or stale geometry), so the results list never changed even
     though the control was correct.
  2. The returned `next_job` pagination stop was classified by `classify_failure`
     with the fill rules, so it became `unknown_exception` ("unexpected exception
     while filling the form") and its bug-log row was filed under
     "Self-Healing — fill" — misleading, since no form was involved (the same
     class of defect BUG-065 fixed for the browse stage).
- **Fix:** in `src/tools/linkedin_pagination.py`, tolerate a click that starts a
  navigation and, when the CDP click does not move the list, retry with the
  control's own DOM `click()` (`_click_control_dom`), which invokes LinkedIn's
  handler directly and bypasses hit-testing. If that also fails, load the next
  results page directly from its `start=25` URL (`next_page_url` /
  `_navigate_to_next_page`), which is deterministic even when every click is
  swallowed. In `src/tools/self_healing/fingerprint.py`, classify a `next_job`
  pagination stop as the new recoverable category `pagination_failed` (symptom
  "the results pagination could not advance"), and in
  `src/tools/self_healing/buglog.py` file `next_job` failures under
  "Self-Healing — next job/pagination". `reload_runtime_modules` now reloads
  fingerprint/capture/buglog as well, so the retry uses the repaired classifier.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_pagination.py` (`_click_control_cdp`,
  `_click_control_dom`, `go_to_next_page`), `src/tools/self_healing/fingerprint.py`
  (`pagination_failed`, `classify_failure`, `symptom_for`),
  `src/tools/self_healing/buglog.py` (`_SCOPE_BY_STAGE`); unit
  `test_go_to_next_page_falls_back_to_a_dom_click`,
  `test_go_to_next_page_reports_no_change_when_neither_click_moves_it`,
  `test_next_job_pagination_stop_is_not_a_form_fill_exception`; live Chrome
  (headless, `AUTOJOB_TASK2_LIVE=1`)
  `test_go_to_next_page_survives_a_swallowed_cdp_click` proves a coordinate CDP
  click on the control is swallowed (the list stays on page 1) while the DOM-click
  fallback advances to page 2; live real-LinkedIn check: loading the computed
  `start=25` URL advanced from page 1 to page 2 and changed the signature; live
  next-job self-heal check: a returned `pagination_failed` stop was captured,
  closed, reopened on the results page, and recovered on attempt 1 with
  `category=pagination_failed`; full unit suite + live Task 2 suite (5/5) + live
  self-healing suite (4/4); bundle `20261027-071134-799022-71afff4f6d5e`;
  commit `(uncommitted)`.
- **Failure fingerprint:** `71afff4f6d5ee9c4ddc1`
- **Occurrences:** 1 (first 2026-10-27T07:11:35+00:00)

### BUG-069 — retry still stopped on pagination and was mis-filed as a fill exception

- **Symptom:** after the first BUG-068 repair, the self-heal retry hit the same
  pagination stop (`the results did not change after clicking next; skipped 20
  applied job(s)`). The second capture was still labelled `unknown_exception`
  ("unexpected exception while filling the form") and filed under
  "Self-Healing — fill", even though the repair had added the `pagination_failed`
  category.
- **Root cause:** two gaps:
  1. The first fix retried the control with a DOM `click()`, but a slow/navigating
     first click could detach the marker, so the DOM retry had no element to
     click. There was no deterministic final fallback.
  2. `reload_runtime_modules` reloaded the browser/fill stack but **not**
     `src.tools.self_healing.fingerprint`, `capture`, or `buglog`. The retry
     therefore kept using the pre-repair classifier, producing the wrong
     `unknown_exception` category/scope.
- **Fix:** `go_to_next_page` now falls back to loading the next results page via
  its `start=25` URL when both clicks fail; the repair reload list now includes
  the fingerprint/capture/buglog modules so classification and filing use the
  repaired code on the very next retry.
- **Status:** 🟡 Fixed (superseded)
  - Superseded by the final BUG-068 fix (DOM click + URL navigation) and the
    self-healing module reload; this entry stays as the evidence for the failed
    retry.
- **Evidence:** `src/tools/linkedin_pagination.py` (`_click_control_dom`,
  `_navigate_to_next_page`, `next_page_url`),
  `src/tools/self_healing/recovery/repair.py` (`_RUNTIME_MODULES`);
  `tests/unit/test_linkedin_pagination.py`
  (`test_go_to_next_page_falls_back_to_url_navigation`),
  `tests/unit/test_task_self_heal.py`
  (`test_repair_reloads_the_self_healing_classifier`); live Chromium check:
  navigating the real results URL to `start=25` loaded page 2 and changed the
  signature. Uncommitted.
- **Failure fingerprint:** `a545c3497393b71a125b`
- **Occurrences:** 1 (first 2026-10-27T07:25:24+00:00)

### BUG-075 — the job search returned no results (interrupted verification run)

- **Symptom:** browse: job search returned no results
- **Root cause:** an artifact of aborting the Task 16 live-verification command mid-search.
  The captured bundle has no page URL, visible text, DOM excerpt, screenshot, or
  run id, so no browser step actually failed; the self-healing guard classified the
  interrupted run as `search_no_results`. The same search returned 25-32 jobs in
  the surrounding successful runs.
- **Fix:** none needed — not a product defect. The verification run was repeated.
- **Status:** ⚪ Won't fix
- **Evidence:** bundle `C:\Users\shakt\OneDrive\Desktop\project\AutoJobApply\data\debug\self_healing\20261028-021109-731935-db70a59559c4` (all diagnostic fields empty); successful Task 16 live runs in the same session.
- **Failure fingerprint:** `db70a59559c47f52d169`
- **Occurrences:** 1 (first 2026-10-28T02:11:09+00:00)

### BUG-077 — unexpected exception while filling the form: another browser is already using the autojobapply profile c:\users\shakt\onedrive\desktop\project\autojobapply\data

- **Symptom:** another browser is already using the AutoJobApply profile C:\Users\shakt\OneDrive\Desktop\project\AutoJobApply\data\profile (process id(s): 14900, 9784, 20796, 13184, 19800, 22284, 16512, 20856, 15340, 2856, 8664, 9552, 19052, 15164, 6496). Close that window (or wait for the other run to finish), then retry; to force-close it run `autojob --clean-profile`.
- **Root cause:** Auto-classified as `unknown_exception` during `browse`; see the bundle for the failing step/DOM. A source-level root cause is still pending.
- **Fix:** Pending. Recorded before any repair attempt.
- **Status:** 🔴 Open
- **Evidence:** bundle `C:\Users\shakt\OneDrive\Desktop\project\AutoJobApply\data\debug\self_healing\20261028-084613-663916-dc66109cf271`; captured 2026-10-28T08:46:13.664916+00:00
- **Failure fingerprint:** `dc66109cf2710429d213`
- **Occurrences:** 1 (first 2026-10-28T08:46:13+00:00)

### BUG-080 — match aborted on a transient LLM connection error

- **Symptom:** `match: the LLM call failed: Connection error.` The resume match for
  Senior Integration Engineer at Cuscal Limited failed during the Task 3.2
  describe/pick call, and the run stopped instead of retrying the LLM request.
- **Root cause:** Task 3.2's `_chat` only retried to strip provider-rejected request
  knobs. A provider/network failure (`Connection error.`, 429 or 5xx) that escaped
  the OpenAI client's own retries was wrapped as `ResumeDescriptionError` and
  surfaced immediately, so one transient blip aborted the whole job. The original
  auto-title came from stale Task 4 state; that mislabel is BUG-081.
- **Fix:** `_chat` now retries transient transport failures a bounded number of
  times (default 2 extra attempts) with exponential backoff before surfacing the
  Task 3.2 error. The retry count and delay are configurable with
  `AUTOJOB_LLM_TRANSPORT_RETRIES` and
  `AUTOJOB_LLM_TRANSPORT_RETRY_BACKOFF_SECONDS`. Deterministic failures (bad
  request/API key, unusable reply) keep their existing handling.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/resume_descriptions/client.py` (`_is_transient_error`,
  `_chat`), `src/configuration.py`; tests
  `tests/unit/test_resume_descriptions/test_client.py`
  (`test_pick_best_resume_retries_a_transient_connection_error`,
  `test_pick_best_resume_retries_an_upstream_5xx`,
  `test_pick_best_resume_does_not_retry_a_deterministic_error`) and
  `tests/unit/test_resume_descriptions/test_describe.py`
  (`test_describe_resume_retries_a_transient_connection_error`); full unit suite,
  live self-healing suite (4/4), and a live OpenRouter describe/match check.
  Bundle `20261029-040724-547258-ad494459285d`; commit `(uncommitted)`.
- **Failure fingerprint:** `ad494459285d836efaf9`
- **Occurrences:** 1 (first 2026-10-29T04:07:25+00:00)

### BUG-081 — match-stage capture reused the previous job's Task 4 outcome

- **Symptom:** the auto-recorded BUG-080 was titled "unexpected exception while
  filling the form: no resume control found on this form step; reached the last
  step..." even though the failure was `match: the LLM call failed: Connection
  error.` The bundle also carried the previous job's email/phone fields, so the
  report pointed at the wrong step.
- **Root cause:** the crash guard passes `working["task4"]` to `capture_failure`
  for every stage, and `capture_failure` folded that stale fill outcome into the
  notes, fields, and fingerprint. The non-fill classifier had no LLM/provider
  category either, so the match error inherited the fill label
  `unknown_exception`.
- **Fix:** `capture_failure` ignores `task4` for non-fill stages, and
  `classify_failure` maps match-stage LLM/network errors to the new
  `llm_call_failed` category. The auto-recorded title now names the real stop.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/self_healing/capture.py`,
  `src/tools/self_healing/fingerprint.py`; tests
  `tests/unit/test_self_healing.py`
  (`test_match_capture_ignores_the_previous_jobs_fill_outcome`) and
  `tests/unit/test_task_self_heal.py`
  (`test_match_llm_failure_is_not_a_form_fill_exception`,
  `test_match_llm_failure_ignores_the_previous_jobs_fill_notes`); full unit suite;
  commit `(uncommitted)`.
- **Failure fingerprint:** none of its own — evidence from the same bundle as
  BUG-080.
- **Occurrences:** 1 (same capture as BUG-080, 2026-10-29T04:07:25+00:00)

### BUG-084 — unexpected exception while filling the form: another browser is already using the autojobapply profile c:\users\shakt\onedrive\desktop\project\autojobapply\data

- **Symptom:** another browser is already using the AutoJobApply profile C:\Users\shakt\OneDrive\Desktop\project\AutoJobApply\data\profile (process id(s): 7136, 680, 12900, 23240, 24732, 13384, 5840, 14392, 16256, 24572, 23184, 20448, 22376, 16652, 21740). Close that window (or wait for the other run to finish), then retry; to force-close it run `autojob --clean-profile`.
- **Root cause:** Auto-classified as `unknown_exception` during `browse`; see the bundle for the failing step/DOM. A source-level root cause is still pending.
- **Fix:** Pending. Recorded before any repair attempt.
- **Status:** 🔴 Open
- **Evidence:** bundle `C:\Users\shakt\OneDrive\Desktop\project\AutoJobApply\data\debug\self_healing\20261031-095239-879180-d86f01b44362`; captured 2026-10-31T09:52:39.879180+00:00
- **Failure fingerprint:** `d86f01b44362b95f1e8a`
- **Occurrences:** 1 (first 2026-10-31T09:52:39+00:00)

### BUG-085 — form did not advance to a new step: no resume control found on this form step; form did not advance to a new step; stopping before submit

- **Symptom:** fill: form did not advance to a new step
- **Root cause:** Auto-classified as `form_did_not_advance` during `fill`; see the bundle for the failing step/DOM. A source-level root cause is still pending.
- **Fix:** Pending. Recorded before any repair attempt.
- **Status:** 🔴 Open
- **Evidence:** bundle `C:\Users\shakt\OneDrive\Desktop\project\AutoJobApply\data\debug\self_healing\20261031-100549-988503-78f4f0ed5dbd`; captured 2026-10-31T10:05:50.338233+00:00
- **Failure fingerprint:** `78f4f0ed5dbdf082c971`
- **Occurrences:** 1 (first 2026-10-31T10:05:50+00:00)

### BUG-090 — form did not advance to a new step: no resume control found on this form step; form did not advance to a new step; stopping before submit

- **Symptom:** fill: form did not advance to a new step
- **Root cause:** Auto-classified as `form_did_not_advance` during `fill`; see the bundle for the failing step/DOM. A source-level root cause is still pending.
- **Fix:** Pending. Recorded before any repair attempt.
- **Status:** 🔴 Open
- **Evidence:** bundle `C:\Users\shakt\OneDrive\Desktop\project\AutoJobApply\data\debug\self_healing\20261101-222000-372226-fb16d860087d`; captured 2026-11-01T22:20:00.798290+00:00
- **Failure fingerprint:** `fb16d860087dee37429e`
- **Occurrences:** 1 (first 2026-11-01T22:20:01+00:00)
