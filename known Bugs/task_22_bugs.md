# Task 22 — Submission mode bugs

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
