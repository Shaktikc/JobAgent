# Task 30 bug log

## T30-004 — Fallback pricing excluded from source control
- **Symptom:** The new fallback pricing file was hidden by Git's runtime-data ignore rule.
- **Root cause:** The rule ignored the entire data directory, including public configuration.
- **Fix:** Ignore data contents with an exception for model_pricing.json.
- **Status:** 🟢 Fixed
- **Evidence:** `.gitignore`; `git check-ignore` verifies pricing is included while runtime files stay ignored. Commit: uncommitted.

## T30-001 ? Metrics reporter stale after browser recovery
- **Symptom:** A replacement browser reporter could leave metrics directed at the old page.
- **Root cause:** Accounting retained the reporter created at initial startup.
- **Fix:** Rebind the metrics publisher when StatusReporter binds a page, preserving totals.
- **Status:** ?🟢 Fixed
- **Evidence:** `src/tools/linkedin_status_overlay/status_reporter.py`; status reporter tests and Task 30 browser check. Commit: uncommitted.

## T30-002 ? Test insertion misplaced repair assertions
- **Symptom:** The new call-site test raised NameError for `status`.
- **Root cause:** Repair assertions were accidentally appended to the next test.
- **Fix:** Restore the assertions to the repair-usage test.
- **Status:** ?🟢 Fixed
- **Evidence:** `tests/test_token_usage_runtime.py`; final pytest run. Commit: uncommitted.

## T30-003 ? Binding a page unexpectedly creates a panel
- **Symptom:** Two existing status reporter tests failed after metrics integration.
- **Root cause:** Rebinding immediately published metrics and invented an activity message.
- **Fix:** Rebinding changes the publisher only; normal activity or metrics updates render it.
- **Status:** 🟢 Fixed
- **Evidence:** `tests/unit/test_status_reporter_latest.py`; full pytest run. Commit: uncommitted.
