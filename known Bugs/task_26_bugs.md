# Task 26 bugs

### BUG-122 — Unknown answers could be saved before completion

- **Symptom:** Partial typing could reach the answer store; checkbox selection could finish early, and Done was enabled without an answer.
- **Root cause:** The original wait loop saved before checking completion and returned partial data on timeout. The inherited partial fix still had a settle timer, lost group identity during marker fallback, and preferred stale event values. Callers could write the completed answer again or replace it with later ticks.
- **Fix:** Require completion before saving/returning, extend inactivity on focus/edit/selection, require Done for groups, disable Done for empty answers, read current scoped values, preserve the confirmed selection, and avoid duplicate store writes. A new pending-status module owns banner feedback. Regression browser profiles use temporary data directories so they can coexist with LinkedIn verification.
- **Status:** 🟢 Fixed. Task status remains in progress awaiting user verification.
- **Evidence:** `src/tools/linkedin_ask_human/`, `src/tools/linkedin_easy_apply_fill/checkbox_groups.py`; `tests/unit/test_task26_completion.py`, `tests/integration/test_task26_completion_live.py`, and expanded Task 24 completion tests. Real LinkedIn Bluebird job `4484022219` on 2026-11-05: seven prefixes checked, zero writes while typing, one complete write after Done, Saved shown, wait returned; original store and control restored. Artifacts: `data/debug/task26/completion.json`, `saved.png`. Reproduce with `scripts/verify_task26_linkedin.py`. Uncommitted; base commit `addac8f`.

### BUG-124 — Done hits the native modal backdrop and opens Save application

- **Symptom:** WNS Easy Apply detected Desktop, Internet, Landline but stayed pending. A physical click on Done opened LinkedIn's “Save this application?” prompt instead of confirming the answer.
- **Root cause:** The top-layer banner was appended outside the native `dialog.showModal()` subtree. Chromium painted the popover but treated it as inert; the click hit the dialog backdrop. Earlier tests used JavaScript `.click()`, which bypassed pointer hit testing. Generic pending feedback also failed to make the required confirmation obvious.
- **Fix:** Mount the banner inside the active native modal while retaining its top-layer popover. List detected checkbox choices and explicitly instruct the human to click Done to save and continue. Keep the existing completion gate and store schema.
- **Status:** 🟢 Fixed; awaiting user verification of Task 26.
- **Evidence:** A real-CDP-click Chromium regression failed with backdrop dismissal before the fix and passed for both Done and Skip afterward (`tests/integration/test_task26_modal_click_live.py`). Feedback regression: `tests/integration/test_task26_completion_feedback_live.py`. Source: `banner_js.py`, `completion_js.py`, `flow.py`. Live WNS job `4487517578` on 2026-11-05: repaired the existing banner, real click reached Done, all three choices persisted, banner disappeared, and no discard/save prompt appeared. Evidence: `data/debug/task26/modal-click-fixed.json`. Uncommitted; base commit `0f63da8`.
