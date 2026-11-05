# Task 26 bugs

### BUG-122 — Unknown answers could be saved before completion

- **Symptom:** Partial typing could reach the answer store; checkbox selection could finish early, and Done was enabled without an answer.
- **Root cause:** The original wait loop saved before checking completion and returned partial data on timeout. The inherited partial fix still had a settle timer, lost group identity during marker fallback, and preferred stale event values. Callers could write the completed answer again or replace it with later ticks.
- **Fix:** Require completion before saving/returning, extend inactivity on focus/edit/selection, require Done for groups, disable Done for empty answers, read current scoped values, preserve the confirmed selection, and avoid duplicate store writes. A new pending-status module owns banner feedback. Regression browser profiles use temporary data directories so they can coexist with LinkedIn verification.
- **Status:** 🟢 Fixed. Task status remains in progress awaiting user verification.
- **Evidence:** `src/tools/linkedin_ask_human/`, `src/tools/linkedin_easy_apply_fill/checkbox_groups.py`; `tests/unit/test_task26_completion.py`, `tests/integration/test_task26_completion_live.py`, and expanded Task 24 completion tests. Real LinkedIn Bluebird job `4484022219` on 2026-11-05: seven prefixes checked, zero writes while typing, one complete write after Done, Saved shown, wait returned; original store and control restored. Artifacts: `data/debug/task26/completion.json`, `saved.png`. Reproduce with `scripts/verify_task26_linkedin.py`. Uncommitted; base commit `addac8f`.
