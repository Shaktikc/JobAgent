# Task 33 — Keep a complete crash log for every crash so it can be debugged later

**Status:** 🟡 In progress


**Goal**

- Whenever the application crashes, write **one durable crash bundle** under
  `data/crash_logs/` before the process exits or the run stops.
- The bundle must contain everything needed to debug without reproducing the
  failure: the full exception chain, timestamp, run/job identity, CLI arguments,
  environment (Python/platform/git commit), a redacted settings snapshot, the
  latest graph state, the last runtime log lines, and — when a live browser
  exists — the page URL/title plus a best-effort screenshot, DOM excerpt, and
  browser console lines.
- Also keep a durable per-run log file, so a crash bundle can reference the
  complete run and not just the last N lines.


