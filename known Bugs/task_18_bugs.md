# Task 18 bugs

## TASK18-001 — Live check looked for the search field too late

- **Symptom:** The first live check loaded 24 `data engineer` results with the
  correct URL, but failed because the final results page had no discoverable
  search input.
- **Root cause:** The test assumed the search field remained present after
  LinkedIn's AI-search detour and filter navigation.
- **Fix:** Observe the real input value immediately after the production fill
  operation, then verify the resulting URL and loaded results separately.
  The test can reconnect to its dedicated browser with `AUTOJOB_TASK18_CDP_URL`.
- **Status:** 🟢 Fixed — guarded by the live test.
- **Evidence:** `tests/integration/test_task18_query_live.py`;
  live check passed against LinkedIn using `data engineer` (24 results, three
  verified input fills, correct query URL); local transcript:
  `data/verification/task18-live.log`. No application was opened
  or submitted. Commit: `fbba030` (Task 18 implementation and live-test fix).
