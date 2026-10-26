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
