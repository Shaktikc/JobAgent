# General bugs (not tied to a single task)

Bugs that cannot be attributed to one Task category: the shared browser session
and browser-use integration, the persistent profile / CDP connection, the CLI,
build/tooling, security, and tests. The graph `cleanup` node and Windows
shutdown noise are here because they affect every task.

See [`bug_log.md`](bug_log.md) for the master index and the entry format.
Status: 🟢 Fixed · 🟡 Fixed (superseded) · 🔴 Open · ⚪ Won't fix

| ID | Area | Symptom (short) | Status | Fix commit(s) |
|----|------|-----------------|--------|---------------|
| BUG-001 | Browser session | browser-use killed the browser between pipeline tasks | 🟢 Fixed | `a175262` |
| BUG-007 | Tests (integration) | `Page.evaluate` needed the arrow-function form | 🟢 Fixed | `24ccc4a` |
| BUG-008 | Tests (unit) | "applied today" test hard-coded a date | 🟢 Fixed | `2cd64a6` |
| BUG-009 | Build | `poetry.lock` out of sync for a clean install | 🟢 Fixed | `43e55f1` |
| BUG-010 | Security | candidate PII resumes committed to git | 🟢 Fixed | `4111f4d` |
| BUG-027 | Browser profile | crashed run's stale lock → "exited before CDP became available" | 🟢 Fixed | `888e11d` |
| BUG-028 | Browser profile | second launch force-killed a live browser → CDP drop (`WinError 1225`) | 🟢 Fixed | `888e11d` |
| BUG-029 | Windows CLI | "I/O operation on closed pipe" noise after a successful run | 🟢 Fixed | `2b60465` |
| BUG-030 | Cleanup | agent closed the browser on timeout (it must never close it) | 🟢 Fixed | `ef2ad44`, `31553e2` |
| BUG-033 | UI overlay | Task 9 status panel rendered behind LinkedIn's Easy Apply modal | 🟢 Fixed | (uncommitted) |
| BUG-041 | Task 8 loop | advanced to the next job without a real submission | 🟢 Fixed | `f928866` |

---

### BUG-001 — browser-use killed the browser between pipeline tasks

- **Symptom:** the CP-B dry-run stalled between pipeline tasks; the answer/fill
  step started against a dead session.
- **Root cause:** `browser-use` closes the browser at the end of every
  `agent.run()`.
- **Fix:** keep the browser alive across tasks (`keep_alive` on the profile/agent),
  added a watchable/demo mode (`slow_mo_ms`), a CDP-level `read_page_text` that
  still works after an agent run, and an `on_step_end` hook that re-attaches a
  stale session and bounds failures.
- **Evidence:** `src/tools/agent_hooks.py`, `src/tools/browser.py`;
  `tests/unit/test_agent_hooks.py` (7 tests). Commit `a175262`.

### BUG-007 — `Page.evaluate` needs the arrow-function form

- **Symptom:** the browser-use integration smoke failed with `ValueError`.
- **Root cause:** browser-use `0.13.10` requires the arrow-function form; the
  Playwright-style bare expressions were rejected.
- **Fix:** use arrow functions and coerce the string result.
- **Evidence:** `tests/integration/test_session_browser.py`. Commit `24ccc4a`.

### BUG-008 — the "applied today" test hard-coded a date

- **Symptom:** `test_count_applied_today_...` only passed on 2026-09-30.
- **Root cause:** the test used `date(2026, 9, 30)` while `set_job_status` stamps
  the real clock.
- **Fix:** derive `date.today()`, matching `_now_iso`'s local-calendar-day prefix.
- **Evidence:** `tests/unit/test_store.py`. Commit `2cd64a6`.

### BUG-009 — `poetry.lock` out of sync

- **Symptom:** a clean install failed after re-verification.
- **Root cause:** `poetry.lock` was not re-synced with `pyproject.toml`.
- **Fix:** re-sync `poetry.lock`.
- **Evidence:** `poetry.lock`. Commit `43e55f1`.

### BUG-010 — candidate PII resumes committed to git

- **Symptom:** real resumes appeared in the repository.
- **Root cause:** resume files were tracked.
- **Fix:** untrack the resumes and gitignore the resume folders.
- **Evidence:** `.gitignore`. Commit `4111f4d`.

### BUG-027 — a crashed run's stale profile lock blocked the next launch

- **Symptom:** `"Browser process … exited before CDP became available"`.
- **Root cause:** an interrupted/crashed run left Chromium's single-instance lock
  in `data/profile` with no live process; the new launch handed its command line
  to a non-existent instance and exited before opening its own CDP port.
- **Fix:** detect a locked profile and clear only a **stale** lock (no process
  references the profile) before launching. `autojob --clean-profile` forces it on
  demand.
- **Evidence:** `src/tools/browser.py` (`build_browser`, `_profile_is_locked`,
  `clear_profile`), `src/configuration.py`
  (`AUTOJOB_SESSION_CLEAN_STALE_PROFILE`); README Troubleshooting. Commit
  `888e11d`.

### BUG-028 — a second launch force-killed a live browser and dropped CDP

- **Symptom:** `CDP WebSocket message handler exited unexpectedly (connection
  closed)` followed by `ConnectionRefusedError: [WinError 1225]`.
- **Root cause:** stale-profile recovery keyed off `_profile_is_locked`, which on
  Windows is true for a **live** browser (Chromium holds `lockfile` while it
  runs). It then ran `taskkill /F /T`, force-closing a browser another run was
  driving.
- **Fix:** separate a **stale** lock from a **live** owner. Clear lock files only
  when no process references the profile; otherwise raise a clear "another browser
  is already using the AutoJobApply profile" error without killing anything.
  `terminate_profile_browsers` is now used only by `autojob --clean-profile`.
- **Evidence:** `src/tools/browser.py`;
  `test_build_browser_refuses_to_kill_a_live_browser_holding_the_profile`,
  `test_build_browser_clears_a_stale_profile_lock`. Commit `888e11d`.

### BUG-029 — "I/O operation on closed pipe" noise after a successful run

- **Symptom:** a Windows `asyncio` unraisable traceback printed after an
  otherwise-successful run.
- **Root cause:** browser-use's Chrome subprocess can leave an asyncio pipe
  transport alive at loop shutdown; its `__del__` raises.
- **Fix:** install a `sys.unraisablehook` that filters exactly that message; other
  unraisables are untouched.
- **Evidence:** `src/main.py` (`_silence_windows_pipe_noise`). Commit `2b60465`.

### BUG-030 — the agent closed the browser on timeout

- **Symptom:** at the terminal step the browser was closed for the human after the
  wait; an interrupted run also left nothing to inspect.
- **Root cause:** cleanup/`wait_for_human_close` called `session.kill()` /
  `close_run()` which closed the window.
- **Fix:** the agent **never** closes the browser. `keep_alive=True` on the
  profile, `_detach_session` releases the CDP handle without killing (clearing the
  watchdog's subprocess handle first), and `close_run`/`release_run` only forget
  the run. At the terminal step the run waits for the human to close the window,
  then **leaves it open** either way. Only `autojob --clean-profile` force-closes.
- **Evidence:** `src/tools/browser.py` (`_detach_session`, `close_run`,
  `wait_for_human_close`, `release_run`), `src/nodes/cleanup.py`,
  `src/tools/linkedin_apply_loop.py`, `src/tools/linkedin_search.py`,
  `src/configuration.py` (`keep_open_timeout_seconds`). Commits `ef2ad44`,
  `31553e2`.

### BUG-033 — Task 9 status panel rendered behind LinkedIn's Easy Apply modal

- **Symptom:** during a real run the "AutoJobApply is working" panel (bottom-left)
  appeared dimmed *behind* the Easy Apply modal's backdrop, while the Task 5
  "does not know this answer" banner (bottom-right) stayed in front.
- **Root cause:** the panel is a top-layer `popover` created when the run starts,
  before the Easy Apply modal (itself a top-layer `<dialog>`) is opened. Per the
  top-layer rules a modal's `::backdrop` is painted above any popover opened
  *before* it, and a plain `showPopover()` on an already-open popover is a no-op,
  so routine updates never moved the panel back to the top. The Task 5 banner
  works because it is first shown *after* the modal, so it is already the newest
  top-layer entry.
- **Fix:** the panel re-raises itself to the newest top-layer slot on every update
  by hiding and re-showing its popover (`hidePopover()` → `showPopover()`), so it
  stays in front of the modal like the Task 5 banner. Both calls run in the same
  synchronous JS task, so there is no visible flicker.
- **Evidence:** `src/tools/linkedin_status_overlay.py` (`_UPDATE_STATUS_JS`); live
  Chromium A/B check with a dark `dialog::backdrop` (panel crisp in front, a plain
  popover dimmed behind). Status: 🟢 Fixed. Commit: (uncommitted).

### BUG-041 — the Task 8 loop could open the next job without a real submission

- **Symptom:** after a job was filled, the loop could move on and open another job
  even though the human had not clicked **Submit**.
- **Root cause:** two stale signals counted as a submission. (a) The fallback
  `card_applied and not form_open` did not check whether the card already read
  **Applied** before the wait, so closing/dismissing the form on a job with a stale
  Applied badge looked like a submit. (b) A previous job's **"Application sent"**
  dialog can still be on the results page when the next wait starts; it was
  detected immediately as the new job's confirmation.
- **Fix:** capture the card state and the visible confirmation when the wait starts.
  A stale confirmation is dismissed and that exact text is ignored; only a **new**
  confirmation counts. The card fallback only counts when the card flips from
  unapplied to Applied **during** this wait. A confirmation dialog still counts
  immediately.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_apply_loop.py` (`submission_detected`,
  `await_human_submit`); `tests/unit/test_linkedin_apply_loop.py`
  (`test_await_human_submit_ignores_a_card_already_applied_before_the_wait`,
  `test_await_human_submit_ignores_a_stale_confirmation_from_the_previous_job`,
  `test_await_human_submit_detects_a_card_flipping_to_applied`). Commit
  `f928866`.
