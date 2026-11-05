# Task 24 — Required-question validation recovery

## BUG-115 — Missing required-group feedback is lost

- **Symptom:** Review can leave an unanswered required radio question open with
  “This field is required”, without an answer banner or safe skip.
- **Root cause:** The feedback detector omitted that wording and stopped after
  four ancestors, missing deeply nested groups' sibling feedback. The correction
  guard also treated missing answers as invalid factual answers.
- **Fix:** Recognise required messages and associate feedback using the live
  question's control boundary, including explicit ARIA references. Resolve missing
  required answers through the existing chooser/banner, verify fresh controls,
  retry navigation once, then use Task 20's durable skip/close path if unresolved.
  A shared tracker bounds chooser calls/prompts across initial fill and recovery.
  Keep default radio/checkbox values out of answer redaction so words such as
  “option” in visible errors are preserved.
- **Status:** 🟢 Fixed — implementation and live verification passed; Task 24
  remains in progress for user verification.
- **Evidence:** `src/tools/linkedin_validation/detection.py`;
  `tests/integration/test_task24_required_detection_live.py`: reproduced failure,
  browser feedback tests cover exact wording, deep groups, hidden/unrelated
  messages and another question's ARIA reference. Five control kinds are verified
  after DOM replacement; automatic/human radio recovery and persistent rejection
  are bounded. `tests/unit/test_task24_recovery.py` covers exceptions, caps,
  optional exclusion and a pending factual correction. Journal/graph tests cover
  durable link/attempt metadata and continuation. Final suite: **832 passed,
  118 opt-in checks skipped**; targeted Chromium runs: **20 passed**, then
  **8 passed** after final shared-completion/recovery changes. Ruff, compilation,
  CLI help and `uv build --out-dir data/task24-build` passed.
  Real Bluebird job `4484022219` reproduced the exact unanswered “Do you use AI
  coding tools daily in your work?*” error, then automatic recovery reached
  “Review your application” in the same form with no skip/submission:
  `data/debug/task24/automatic.json`, `inspection.json`, `inspection.html`.
  The disabled-human real-site path on job `4476996437` saved the canonical link
  and required error, closed the form and returned without a crash:
  `data/debug/task24/disabled.json`, `data/invalid_input_skips.json`.
  Some browser runs emit the existing Windows asyncio pipe-cleanup warning;
  the final real-site screenshot capture timed out, with DOM/JSON evidence kept.
  Commit: uncommitted, base `addac8f`.

## BUG-116 — An unfinished human answer is saved or reused after Skip/timeout

- **Symptom:** The shared banner saved a typed prefix before the user finished;
  recovery could later adopt that remaining partial form value as a prefilled
  answer after the human skipped or timed out.
- **Root cause:** Task 5 saved on any non-empty poll and returned `last_saved`
  on timeout. Its reader marked text reached through markers as atomic. Recovery
  did not distinguish a committed prefill from a failed human attempt.
- **Fix:** Keep completion/persistence in Task 5: require blur/Enter/Done for
  text and Done for multi-checkbox selections; preserve pending edits only in
  memory, extend the inactivity deadline on interaction, and never return/save
  unfinished values. Recovery preserves failed-human-attempt state and skips
  instead of adopting the leftover partial value or navigating with it.
- **Status:** 🟢 Fixed — guarded by tests. Task 26 is in progress as a shared
  prerequisite; its separate real-site text verification and user approval remain.
- **Evidence:** `src/tools/linkedin_ask_human/{flow,answer_js,banner_js,store}.py`,
  `src/tools/linkedin_validation/{required_answers,navigation}.py`;
  `tests/unit/test_browser_tools/test_human_banner.py` and
  `tests/unit/test_task24_recovery.py` each reproduced a failure before its fix.
  `tests/integration/test_task24_human_completion_live.py` verifies input-only
  prefixes stay unsaved, Done/blur store the final value, timeout stores nothing,
  and multi-checkbox selection waits for Done and saves the complete group.
  Final unit/full-suite and browser results are recorded under BUG-115.
  Commit: uncommitted, base `addac8f`.

## BUG-117 — An offscreen recovery retry can be consumed by scrolling

- **Symptom:** Clicking a footer below the visible form can scroll it into view
  without advancing, consuming the only validation retry.
- **Root cause:** Browser-use can calculate click coordinates before scrolling.
- **Fix:** Explicitly scroll the freshly resolved Next/Review control into view
  before clicking during recovery. Keep the navigation retry bound to one.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/linkedin_validation/navigation.py`;
  `tests/integration/test_task24_recovery_live.py` places the footer 1500 pixels
  below the question and verifies one retry, success or persistent failure,
  for both chooser and human answers. Real LinkedIn footer inspection reproduced
  the scroll-without-advance behavior during setup. Task 24 recovery reached
  review without submitting. Commit: uncommitted, base `addac8f`.
