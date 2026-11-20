# Task 8 — Application loop bugs

### BUG-128 — A missing résumé attachment ended the job scan

- **Symptom:** The run ended with “resume was not attached” after filling one posting and left later jobs unprocessed.
- **Root cause:** The fill node added a run-wide error for the missing attachment. The graph routed directly to cleanup. A separate default also capped successful runs at 35 submissions.
- **Fix:** Record the missing attachment as a per-job skip, exclude the posting on subsequent scans, and reuse the existing form-close and next-job path. The default submission cap is now zero (unlimited).
- **Status:** 🟢 Fixed
- **Evidence:** src/nodes/missing_resume.py, src/nodes/fill.py, src/nodes/apply_loop.py and tests/unit/test_missing_resume_loop.py. Live LinkedIn search with a supplied missing-attachment outcome excluded unapplied posting 4491825129 and selected 4488282369. No submission attempted. Uncommitted on base 7ae0ebe.
