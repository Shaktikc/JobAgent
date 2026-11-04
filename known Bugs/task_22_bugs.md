# Task 22 — Submission mode bugs

### BUG-114 — Offscreen resume controls prevented automatic submission

- **Symptom:** the Redbelly Network run reached final review with `resume=none`
  and stopped with `fill: resume was not attached`. The review retained a
  different saved resume from the Go resume selected by matching.
- **Root cause:** browser-use calculates click coordinates before scrolling.
  The Upload resume button below a long saved-resume list was missed. Listed
  resume controls had the same defect and could report selection without a click.
  The submit node was never reached; the manual input-handoff change was not
  responsible for this reproduced failure.
- **Fix:** scroll and settle both listed-resume and upload controls before
  invoking the browser click, using the same ordering as terminal submission.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/linkedin_easy_apply_fill/resume_attachment.py`;
  `tests/integration/test_task22_resume_scrolling_live.py`: both cases failed
  before the fix with zero clicks, then passed with the interaction lock active.
  Existing automatic/manual submission and review checks also passed: 13 browser
  checks total. Full suite: 811 passed, 101 skipped. Ruff and wheel build passed.
  Live inspection: Redbelly Network job `4486091668`; initial metadata and
  screenshot retained in `data/debug/task22/resume-controls.*`.
  The fixed walk uploaded `ShaktiKC_Resume_Go.pdf`, reached final review, and
  passed submit readiness on that real posting. Screenshot and result are in
  `data/debug/task22/resume-fixed-live.*`; the real application was not submitted.
  Fix is uncommitted, based on `b560bb6`; no commit was requested.

### BUG-106 — A valid checkbox answer could block automatic submission

- **Symptom:** the initial automatic preflight treated an unchecked option as an
  unanswered required question even when another option in that question was selected.
- **Root cause:** it grouped checkbox options by individual input name. Some
  forms give each option a different name while sharing one question.
- **Fix:** use the fill walk's existing checkbox group keys and counts when
  checking current required answers, so fill and submission agree.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/linkedin_auto_submit.py`; checkbox-group regression in
  `tests/unit/test_task22_auto_submit.py`; full suite: 768 passed, 88 skipped.
  Task 22 Chromium checks: 5 passed. Fix is uncommitted, based on `128eb75`;
  no commit was requested.

### BUG-107 — Manual-mode verification summary changed during Task 22 integration

- **Symptom:** the existing manual-run verification regression failed because
  its successful summary changed from `(not submitted)`.
- **Root cause:** adding the automatic confirmation summary also rewrote the
  manual-mode output, breaking its existing contract.
- **Fix:** retain the established manual summary and add the automatic confirmation
  text only for a confirmed automatic submission.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/nodes/verify.py`;
  `tests/unit/test_graph.py::test_verify_passes_when_all_criteria_are_met` and
  `tests/unit/test_task22_loop.py`; full suite: 768 passed, 88 skipped.
  Fix is uncommitted, based on `128eb75`; no commit was requested.

### BUG-109 — Submission confirmation missed re-rendered semantic job cards

- **Symptom:** the run reported an unconfirmed CORTO application and zero submitted
  jobs, while the posting subsequently showed Application submitted. Browser
  regressions reproduced the same timeout despite a successful Applied card flip.
- **Root cause:** the card probe depended on classic CSS or temporary selection
  markers that React can remove. It normalized the card and target title
  differently and did not handle the selected card's `Selected,` prefix. An
  already-present page-wide submitted status correctly could not confirm a new
  application, leaving no recognized fresh signal.
- **Fix:** inspect semantic role-button cards directly; normalize the selection
  prefix and Verified job badge on both titles; require the correct title and
  company together. Keep the stale-signal and closed-form checks.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/linkedin_submission.py`,
  `tests/integration/test_task22_confirmation_live.py`,
  `tests/unit/test_linkedin_submission.py`; failures reproduced before each fix.
  The affected live posting is `4486453355`; metadata and screenshot are in
  `data/debug/task22/reported-job-search.*`. The original browser had closed, so
  its exact click timeline is unavailable. Final checks: 773 passed, 93 skipped;
  16 opt-in browser checks passed; live card and submitted status both detected.
  Fix is uncommitted, base `128eb75`.


### BUG-110 — An offscreen Submit button was scrolled after coordinates were calculated

- **Symptom:** the automatic attempt returned unconfirmed with no Submit event,
  even though the browser scrolled the button into view. The controlled Chromium
  reproduction recorded zero clicks, matching the reported timeout message.
- **Root cause:** browser-use calculates and clamps click coordinates before its
  internal scroll. When the review footer starts below the viewport, the scroll
  changes its position and the saved click point misses it.
- **Fix:** explicitly scroll the verified terminal button into view and settle
  layout before the actor calculates coordinates; recheck readiness, then click once.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/linkedin_auto_submit.py`,
  `tests/integration/test_task22_submit_scrolling_live.py`; saved before/after
  geometry in `data/debug/task22/scroll-click-before-fix.json` and `scroll-click.json`.
  The regression fails before the fix and passes after it with exactly one click.
  Final checks: 773 passed, 93 skipped; 16 browser checks passed.
  Fix is uncommitted, base `128eb75`.

### BUG-111 — An uncertain automatic submission was reported as a completed run

- **Symptom:** after an automatic timeout, verification reported normal completion
  and no failure evidence was retained for diagnosis.
- **Root cause:** Task 8 only stored a stop reason. Verification accepted every
  recorded stop as success, without distinguishing an uncertain submit from a clean
  cap, exhausted search, or manual handoff.
- **Fix:** retain the last submission result and return `needs_review` for blocked,
  unconfirmed, closed, or interrupted automatic attempts. Preserve metadata,
  button geometry, recent resource statuses and a screenshot on submit failures;
  record its path in the run log. JSON excludes answers and confirmation prose.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/state_loop.py`, `src/nodes/apply_loop.py`,
  `src/nodes/submission_guard.py`, `src/nodes/verify.py`,
  `src/tools/linkedin_submission_evidence.py`;
  `tests/unit/test_task22_failure_reporting.py`; all 773 tests and 16 enabled
  browser checks passed. Ruff and wheel build passed.
  Fix is uncommitted, base `128eb75`.

### BUG-113 — The final review page kept ignoring mouse and keyboard input

- **Symptom:** the terminal Easy Apply review showed an enabled Submit button,
  but the retained browser ignored user input. Controlled Chromium reproduced
  zero raw clicks during the fallback review wait. Some stopped manual waits
  also left the open page locked.
- **Root cause:** the fallback `wait_for_human_close` path never released the
  automation input lock, while the normal submit wait always re-locked on exit,
  even when no automation would continue. A delayed reporter installation could
  re-lock after handoff; cancellation during the CDP unlock could discard the
  registered lock before the renderer accepted the unlock. Waiting for that
  response without a deadline could also stall cancellation after a CDP failure.
- **Fix:** release input before the final fallback handoff and browser detachment;
  restore the manual submit lock only after confirmed submission. Drain pending
  reporter installation and finish unlocking before propagating cancellation,
  with 15-second limits for an unresponsive installer or unlock response.
  Split the oversized browser module by concern, retaining its public and lazy
  exports, unchanged query literals, shared registry, and updated patch targets.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/browser/runs.py`, `src/tools/linkedin_apply_loop.py`,
  `src/tools/linkedin_status_overlay/interaction_lock.py` and `status_reporter.py`;
  `tests/unit/test_task22_review_handoff.py`,
  `tests/unit/test_task22_review_handoff_races.py`,
  `tests/unit/test_task22_review_disconnect.py`,
  `tests/integration/test_task22_review_handoff_live.py`. Before-fix failures:
  six handoff unit cases, four Chromium cases, and four cancellation/install
  race cases, plus six unresponsive-CDP cases. Real LinkedIn job `4486034143` was
  walked to final review without
  submitting: raw mouse/keyboard counts were 0/0 while locked, 1/1 during
  handoff, and 2/2 after timeout; the application stayed open. Evidence is in
  `data/debug/task22/linkedin-review-handoff.json` and the controlled browser
  screenshots. Final checks: 811 passed, 99 skipped; 17 enabled browser checks
  passed. Ruff and the wheel build passed. All edited code files stay below
  415 lines. Fix is uncommitted, based on `b560bb6`; no commit was requested.
