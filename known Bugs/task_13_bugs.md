# Task 13 — Bugs (Date posted → "Past 24 hours")

Bugs whose root cause is in **Task 13**: selecting LinkedIn's **Date posted**
filter and proving the results list is actually limited to the last 24 hours.

See [`bug_log.md`](bug_log.md) for the master index and the entry format.
Status: 🟢 Fixed · 🟡 Fixed (superseded) · 🔴 Open · ⚪ Won't fix

| ID | Symptom (short) | Status | Fix commit(s) |
|----|-----------------|--------|---------------|
| BUG-071 | a checked "Past 24 hours" radio was accepted even though the results URL was not filtered | 🟢 Fixed | (uncommitted) |

---

### BUG-071 — a checked date radio was accepted without an applied filter

- **Symptom:** a live Task 1 run reported `date_posted_filter_selected=True`
  with empty notes, but its results URL had no `f_TPR`; Task 2 then opened a job
  marked **"3 weeks ago"** (unfiltered results). After the fix, a live run's URL
  carried `f_AL=true&f_TPR=r86400` and Task 2 opened an Easy Apply job posted
  **"1 minute ago"**.
- **Root cause:** `date_posted_filter_selected` treated a checked **Past 24
  hours** radio as success. On LinkedIn's AI/semantic results page the date
  popover can render with the option checked without **Show results** applying
  it to the results, so a checked option (or a relabelled pill) alone is not
  proof the list was filtered. Separately, re-selecting Easy Apply by clicking
  its pill after applying the date could reload the page and drop `f_TPR`.
- **Fix:** `select_past_24_hours` now verifies the **applied** range through
  `date_posted_filter_applied` (the URL must contain `f_TPR=r86400`); a checked
  option alone falls through to the documented URL fallback. After the date
  filter, Easy Apply is re-selected through the URL
  (`select_easy_apply_filter(..., prefer_url=True)`) so appending `f_AL=true`
  preserves `f_TPR`; the orchestrator then does a final combined check and
  re-applies whichever filter the reload reset.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_date_posted.py`
  (`date_posted_filter_applied`, `select_past_24_hours`),
  `src/tools/linkedin_search/orchestrator.py` (final combined filter check),
  `src/tools/linkedin_search/easy_apply_filter.py` (`prefer_url`),
  `tests/unit/test_linkedin_date_posted.py`
  (`test_date_posted_filter_applied_requires_the_url_param`,
  `test_checked_option_without_url_falls_back_to_filtered_url`,
  `test_easy_apply_url_reselection_keeps_the_date_range`),
  `tests/integration/test_date_posted_live.py`, and the live Task 1/Task 2 run
  (URL `f_AL=true&f_TPR=r86400`; job posted "1 minute ago"). Uncommitted.
