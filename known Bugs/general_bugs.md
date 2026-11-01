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
| BUG-054 | Task 8 loop | post-apply "resume to profile" promo modal not closed → no next job | 🟢 Fixed | (uncommitted) |

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
- **Evidence:** `src/tools/linkedin_status_overlay/panel_js.py` (`_UPDATE_STATUS_JS`); live
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

### BUG-054 — the post-apply "resume to profile" promo modal was not closed

- **Symptom:** after the human clicked **Submit application**, LinkedIn showed a
  dialog titled **"Your application was sent to <company>!"** that also pitched a
  resume promo — **"Turn your resume into a profile that recruiters notice"** —
  with the buttons **Not now** and **Update profile** (and an X). The agent did
  not close it, so its backdrop stayed over the results list and the Task 8 loop
  could not open the next unapplied job.
- **Root cause:** the dismissible-control labels the agent looked for were only
  **done / dismiss / close / got it**. LinkedIn's newer post-apply dialog declines
  the promo with **Not now**, which matched none of them, so the agent never
  clicked the closing control (the X is not consistently present/labelled on this
  variant). Nothing then removed the dialog before Task 2 re-read the cards.
- **Fix:** recognise **Not now** (and **no thanks / maybe later / skip**) as exact
  safe-dismiss labels in the submission probe, and prefer them over the X/Done so
  the promo is declined; the probe still never matches **Update profile** or
  anything that submits. `_dismiss_confirmation` now retries (bounded) so a second
  dialog that appears after the first also closes, and `open_next_job` dismisses
  any leftover post-apply dialog (via the new `dismiss_post_apply_modals`) before
  re-reading the cards and opening the next job.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_apply_loop.py` (`is_dismiss_label`,
  `_DISMISS_HINTS`, the `_SUBMISSION_QUERY_TEMPLATE` dismiss regex,
  `_dismiss_confirmation`, `dismiss_post_apply_modals`, `open_next_job`);
  `tests/unit/test_linkedin_apply_loop.py`
  (`test_is_dismiss_label_accepts_only_closing_controls`,
  `test_await_human_submit_dismisses_the_resume_promo_with_not_now`,
  `test_dismiss_post_apply_modals_clicks_not_now`,
  `test_dismiss_post_apply_modals_is_a_noop_without_a_dialog`);
  `tests/integration/test_apply_loop_live.py` (opt-in live Chromium fixture
  reproducing the exact dialog: detects the submission, clicks **Not now**, never
  the X or **Update profile**, and closes the modal). Commit (uncommitted).

### BUG-060 — a real submission was never detected: stuck on "waiting for you to submit"

- **Symptom:** on the live LEAP Legal Software application the human clicked
  **Submit** and LinkedIn showed **"Your application was sent to LEAP Legal
  Software!"**, but the agent stayed on *"Task 8: waiting for you to submit this
  application yourself …"* for the rest of the wait and never opened the next job.
  The details pane already read **Application submitted** and the job's card was
  **Applied**.
- **Root cause:** four compounding gaps in the submission probe:
  1. LinkedIn's SDUI confirmation is a bare native `<dialog>` with hashed classes
     (no `role="dialog"`, no artdeco hooks), so the dialog scan found nothing.
  2. `findApplyRoot()` mistook that confirmation for the open Easy Apply form (its
     text contains "application"), so `form_open` stayed true and blocked the card
     fallback.
  3. The card fallback matched cards by **title substring**: for "Software
     Engineer" it picked the *first* card containing that text — an already-Applied
     **"Senior Software Engineer"** job — so the real card's flip looked stale.
  4. The details pane's plain **"Application submitted"** status was not read at
     all.
- **Fix:** new `src/tools/linkedin_submission.py` (split out of
  `linkedin_apply_loop`, which re-exports it): the probe now scans native
  `<dialog>`, `[role="alertdialog"]`, `[aria-modal="true"]` and artdeco containers;
  a dialog carrying a confirmation is never treated as the open form; a short
  visible heading/paragraph can confirm when the dialog has no dismiss label; the
  details pane's **"Application submitted"** is read as its own signal (with a
  baseline); and the card fallback matches the card's exact **title line** (with
  optional company disambiguation), so a longer-titled card is never picked.
  `await_human_submit` passes the new status baseline through
  `submission_detected`.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_submission.py`
  (`_SUBMISSION_QUERY_TEMPLATE`, `submission_detected`, `read_submission_state`),
  `src/tools/linkedin_apply_loop.py` (`await_human_submit` baselines);
  `tests/unit/test_linkedin_submission.py` (status/dialog/card rules),
  `tests/unit/test_linkedin_apply_loop.py` (probe mapping);
  `tests/integration/test_apply_loop_live.py` (three new live Chromium fixtures:
  native-dialog confirmation, status-pane confirmation, correct-card flip). Live
  check against the real already-submitted page returned
  `form_open=false, status_submitted=true, card_applied=true` → detection `True`.
  Uncommitted.

### BUG-061 — closing the browser left the submit wait hung forever

- **Symptom:** after the human closed the stuck browser window, the run process
  stayed alive and idle instead of ending ("the human closed the browser"); it had
  to be killed manually.
- **Root cause:** `await_human_submit` polls with `page.evaluate` through
  browser-use, and a call in flight on a dead CDP link never returns. The loop had
  no timeout on that call, and `is_cdp_connected` can still report `true` after the
  process dies, so the wait blocked forever.
- **Fix:** every submission-state read is bounded (`asyncio.wait_for`, 15 s); three
  consecutive unresponsive reads — or a disconnected session — end the wait with
  `"closed"` (and forget the run). The timeout-path `close_run` is bounded too, so
  a dead link can never hang the final detach.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_apply_loop.py` (`_read_state`,
  `_READ_TIMEOUT_SECONDS`, `_MAX_UNRESPONSIVE_READS`, `await_human_submit`);
  `tests/unit/test_linkedin_submission.py`
  (`test_await_human_submit_ends_when_the_page_stops_responding`, using a page
  whose `evaluate` never returns). Uncommitted.

### BUG-063 � the loop stopped on page 1 when unapplied cards had no Easy Apply

- **Symptom:** after the human submitted the second job, `next_job` logged
  `jobs_seen=24 ... applied_skipped=21 ... pages_visited=1` and stopped with
  "skipped 21 applied job(s); no unapplied Easy Apply job was opened". The three
  remaining unapplied cards offered no Easy Apply control, but the loop never
  checked the next results page.
- **Root cause:** `_task2_on_page` only paginated when **every** card on the
  current page was Applied (`applied_skipped >= cards_seen`). A page with
  unapplied-but-unusable cards (external apply, no Easy Apply button, or a pane
  that did not switch) looked like a reason to stop instead of a reason to keep
  searching.
- **Fix:** paginate whenever a scanned page produced no openable Easy Apply job
  (`cards_seen > 0` and `scan.opened` false), while keeping the page cap, the
  next-page-change check, and the "never open a job just by paginating" rule.
  The final note now says "no openable Easy Apply job was found" instead of
  claiming every job was Applied.
- **Status:** ?? Fixed
- **Evidence:** `src/tools/linkedin_job_selection.py` (`_task2_on_page`),
  `tests/unit/test_browser_tools.py`
  (`test_task2_paginates_when_unapplied_cards_have_no_easy_apply`), plus the
  existing whole-page-Applied pagination tests. Live Chromium check with a
  two-page fixture: page 1 = 1 Applied + 1 external (no Easy Apply), page 2 =
  QA Engineer with Easy Apply → `pages_visited=2`, opened **QA Engineer**, form
  opened. Uncommitted.

### BUG-066 - pagination missed the new LinkedIn results UI, then stopped without healing

- **Symptom:** after submitting 4 jobs the run logged
  `next_job: ... applied_skipped=22 ... pages_visited=1` and stopped with
  "skipped 22 applied job(s); no unapplied Easy Apply job was opened". The console
  returned to the prompt and self-healing never ran, even though 99+ results and a
  page-2 control were visible.
- **Root cause:** the current LinkedIn results page hashes its CSS class names and
  renders the pagination as plain buttons ("Page 1", "Page 2", "Next") outside the
  old `.artdeco-pagination` / `nav[aria-label*=pagination]` containers. The query
  also required `aria-label="Page N"`, so it found no controls. `_task2_on_page`
  reported that as a clean "no job" stop, and `next_job` only had the exception
  crash guard, so the returned pagination failure never entered self-healing.
- **Fix:** discover pagination by grouping page-number/Next buttons that share a
  parent, with or without class names/aria-labels; include the page URL in the
  results signature; report a recoverable pagination failure from
  `go_to_next_page`; and wrap `next_job` with the task-level guard so a failed
  pagination interaction is recorded, the browser is closed/reopened, and the
  same results page is retried. A genuine "no next results page" remains a clean
  stop.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_pagination.py` (`_PAGINATION_QUERY`,
  `_RESULTS_SIGNATURE_JS`, `go_to_next_page(..., reason_out=...)`),
  `src/tools/linkedin_job_selection.py` (`_task2_on_page`),
  `src/nodes/task_self_heal.py` (`_next_job_reason`), `src/graph.py`;
  `tests/unit/test_linkedin_pagination.py`,
  `tests/unit/test_task_self_heal.py`,
  `tests/unit/test_browser_tools.py`; live Chromium checks: (1) a hashed-class
  Page 1/Page 2/Next fixture found the controls, clicked Next, and detected
  `page=2`; (2) the real LinkedIn results page (99+ results) reported
  `Page 1/Page 2/Page 3/Next` and selected `Next`. Uncommitted.

### BUG-067 - human input could change the page while the agent was working

- **Symptom:** using the mouse/keyboard in the live browser while the agent was
  searching, opening jobs, or filling a form could steal a click, change focus, or
  close/navigate the page, making the automation fail or repeat a step.
- **Root cause:** the browser stayed fully interactive during automation; only the
  Task 9 status panel was read-only. There was no input lock around the agent's
  work and no explicit unlock for the steps that genuinely need the human.
- **Fix:** a per-page `InteractionLock` uses CDP `Input.setIgnoreInputEvents` to
  ignore physical input. Browser-use's own `Input` commands are wrapped so the
  lock opens for exactly one automation command and re-locks immediately, so the
  agent can still click/type while the human cannot. The lock auto-unlocks on the
  LinkedIn login/authwall pages, explicitly unlocks for Task 3.1 resume upload,
  Task 5 answer banners, and Task 8 submit waits, and is released on cleanup or a
  failed browse.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_status_overlay/` (`InteractionLock`,
  `begin_human_turn`, `end_human_turn`, `release_interaction_lock` in
  `interaction_lock.py`), `src/tools/linkedin_ask_human/__init__.py`,
  `src/tools/linkedin_best_matching_resume/selection.py`,
  `src/tools/linkedin_apply_loop.py`, `src/nodes/browse.py`;
  `tests/unit/test_linkedin_status_overlay.py`; live Chromium check: after the
  lock was installed an agent CDP click still incremented the page counter while
  physical input was ignored. Uncommitted.

### BUG-070 - the self-heal repair agent stopped on an approval question

- **Symptom:** the second self-heal attempt ended with
  `self-heal(next_job): repair/test: repair command failed with exit code 1` and
  then stopped. The repair log showed the agent had grown
  `linkedin_pagination.py` past 415 lines and asked whether to split it into a
  package; the question was dismissed, so OpenCode exited 1.
- **Root cause:** the repair prompt told the autonomous agent to keep files under
  415 lines and split when larger, but did not tell it that the repair session is
  non-interactive and must never ask a question. The file had also been allowed to
  grow to 454 lines before the question, so the agent could not satisfy both rules
  without approval.
- **Fix:** `scripts/self_heal_repair.py` now tells the repair agent it is running
  non-interactively, must never ask the user a question, must first compact
  redundant comments/docstrings, and must not create new files/packages or edit
  `task/`. `src/tools/linkedin_pagination.py` was compacted back to 408 lines.
- **Status:** 🟢 Fixed
- **Evidence:** `scripts/self_heal_repair.py` (`build_prompt`),
  `tests/unit/test_self_heal_repair.py` (non-interactive prompt assertion);
  `src/tools/linkedin_pagination.py`; full unit suite passes; uncommitted.

### BUG-083 - the human could not type while the run waited for an answer

- **Symptom:** during a real Easy Apply run the Task 5 banner asked *"How many
  years of work experience do you have with GraphQL?"* and the status panel said
  *"Waiting for you - I do not know ... answer it in the form on the page."*, but
  the human could not click or type on the LinkedIn page at all. The fields the
  automation had already filled (Next.js = `7`, .NET Framework = `5`) were there;
  the field that needed a human answer stayed empty.
- **Root cause:** the BUG-067 `InteractionLock` had two ways to send
  `Input.setIgnoreInputEvents(true)` *after* `begin_human_turn` had sent
  `ignore=false`:
  1. the 0.6 s watch loop checked `_human_depth`, then awaited `_on_login_page()`
     (two CDP round trips) before applying its now-stale decision — a human turn
     that began inside that window was re-locked for its whole duration;
  2. the wrapped CDP input command's `finally` re-locked unconditionally when a
     human turn started while the command was still in flight.

  Nothing re-unlocked afterwards because the watch loop skips while a human turn
  is open, so the page stayed deaf until the turn ended.
- **Fix:** all `setIgnoreInputEvents` writes are serialized behind one lock and
  re-check `_human_depth` at write time, so a human turn always wins; the watch
  tick re-checks after its page probe; the automation wrapper ends with the same
  guarded apply instead of a raw re-lock. The watch loop was split into a
  `_refresh()` tick so the race is testable deterministically. While touching the
  415-line module it was split into the `src/tools/linkedin_status_overlay/`
  package (`panel_js`, `status_reporter`, `interaction_lock`).
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_status_overlay/interaction_lock.py`
  (`_ignore_lock`, `_apply`, `_refresh`, the wrapped input command),
  `src/tools/self_healing/recovery/repair.py` (`_RUNTIME_MODULES` reloads the new
  submodules); `tests/unit/test_linkedin_status_overlay.py`
  (`test_watch_tick_in_flight_cannot_re_lock_a_human_turn`,
  `test_automation_command_tail_cannot_re_lock_a_human_turn`,
  `test_apply_true_during_a_human_turn_keeps_the_page_interactive`,
  `test_watch_tick_does_not_probe_the_page_during_a_human_turn`,
  `test_nested_human_turns_stay_unlocked_until_the_last_one_ends`; the first
  three fail against the pre-fix code);
  `tests/integration/test_human_turn_unlock_live.py`; live Chromium check on the
  real paused application: install → watch tick in flight → `begin_human_turn` →
  the last write stayed `ignore=false` after the tick, and a native
  (Windows `SendInput`) Shift keydown reached the page. Uncommitted.
