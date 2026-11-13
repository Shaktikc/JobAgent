# Task 28 bugs

### BUG-125 — Runtime log lines leave the browser status empty or stale

- **Symptom:** Ordinary job-skip/open log lines appeared in the CLI but not in
  the panel. Concurrent updates could pile up, duplicate work, or recreate the
  panel after cleanup. Handoff and recovery paths could bypass the live reporter.
- **Root cause:** `StatusReporter.__call__` was intentionally CLI-only; updates
  used independent untracked tasks, and binding did not replay earlier messages.
  Cleanup passed `print`, and recovery could retain the previous run's callback.
- **Fix:** Mirror runtime messages through one coalescing pump, remember the latest
  message for binding, deduplicate successful renders, and cancel pending updates
  before clearing. Sanitize panel-only text, redact obvious credential shapes,
  and distinguish agent, LLM, and human-waiting activity. Route handoff/recovery
  messages to the current reporter. CLI message text is unchanged.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/linkedin_status_overlay/`, `src/nodes/cleanup.py`,
  `src/nodes/self_heal_guard.py`, `src/tools/browser/runs.py`, and
  `src/tools/self_healing/recovery/reopen.py`; regression tests in
  `tests/unit/test_status_reporter_latest.py`, `test_status_panel_text.py`,
  `test_linkedin_status_overlay.py`, and `test_task28_handoff.py`.
  `scripts/verify_task28_status.py` passed against both the existing Task 2
  fixture in Chromium and the real LinkedIn results page. DOM/terminal comparisons
  and screenshots are in `data/debug/task28/{fixture,linkedin}/`. The fixture
  exercised an Applied skip; LinkedIn selected an unapplied job and verified the
  opening line. LLM/waiting messages were explicit display probes (no model call).
  Both checks verified one panel, purple/amber styling, pointer passthrough,
  aria-live, top-layer visibility, newest burst text, and removal after cleanup.
  No application was submitted; browsers were left open. Browser-use emitted
  Windows pipe-finalizer warnings after successful checks and detachment.
  Full suite: **936 passed, 135 skipped** (opt-in integrations); Ruff and
  `git diff --check` passed; `uv build` produced the source distribution and wheel.
  Changes are uncommitted, based on commit `0059323`.

Task 28 supersedes Task 9's CLI-only technical-detail display rule. Task 9's
specification is unchanged. Task completion still requires user verification.

### BUG-126 — Status body is rendered below the visible browser window

- **Symptom:** User screenshots `Screenshot 2026-11-13 183159.png` and
  `Screenshot 2026-11-13 183154.png` show only the panel heading above the Windows
  taskbar while the terminal says `Please wait - filling form step 3...`.
- **Root cause:** `build_browser` configured a fixed 1280×800 emulated viewport
  for visible as well as headless sessions. Browser-use's tab-created handler
  applies that size even when the native window is smaller. The bottom-fixed
  panel is positioned relative to the emulated page, outside the visible window.
  Earlier Task 28 checks verified DOM text and page screenshots, which can
  include pixels below the actual window; they missed physical visibility.
- **Fix:** Visible sessions use the native window's content dimensions with
  `no_viewport=True` and no emulated viewport. Configured width/height set the
  initial window size. Headless sessions retain their configured fixed viewport.
  The live harness now checks the panel body against the visible window and can
  open Easy Apply for a display-only check, without filling or submitting.
- **Status:** 🟢 Fixed.
- **Evidence:** `src/tools/browser/profiles.py`,
  `tests/unit/test_browser_viewport.py`, and
  `tests/integration/test_status_viewport_live.py`. Both the headed profile test
  and live geometry regression failed before the fix. The live regression
  exercises browser-use's real tab-created handler and resizes the native window
  twice. Before: page height 800, outer window heights 640/540, status text bottom
  760 (off-screen). After: page heights 547/447, status text bottoms 507/407,
  visible after both resizes without emitting another message. Metrics and
  screenshots: `data/debug/task28/viewport/{before,after}*`.
  Real LinkedIn Easy Apply verification passed using
  `scripts/verify_task28_status.py --linkedin --open-form`: body bottom 667
  within a 707-pixel visible page; screenshot
  `data/debug/task28/linkedin/form-visible.png`. The quoted step-3 line was
  replayed as a display probe with the real modal open; no fields were filled
  and no application was submitted. Full suite: **938 passed, 136 skipped**;
  the opt-in live viewport regression was also run separately and passed.
  Ruff, `git diff --check`, and `uv build --wheel` passed.
  Commit: uncommitted changes based on `0059323`. BUG-125's log mirroring remains
  in place; this fixes a separate browser-sizing defect exposed by user review.
