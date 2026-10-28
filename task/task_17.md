# Task 17 — Ask for Past 24 hours or Past week first, then fall back to the other range

**Status:** ✅ Done

**Goal:** At startup the agent asks whether to search **Date posted → Past 24
hours** or **Date posted → Past week** first. It scans the chosen range and, when
every job in that range has been scanned and no openable (unapplied, Easy Apply)
job is left, falls back to the other range:

- chose **Past 24 hours** → fall back to **Past week**;
- chose **Past week** → fall back to **Past 24 hours**.

The fallback happens once per scan. A later scan that is already on the fallback
range keeps scanning that range and does not bounce back to the primary range.
The week list includes the 24-hour jobs, so applied/skipped keys carry over and
those jobs are never reopened. The agent **never** clicks **Submit application**.

**Preconditions**
- The CLI startup step asks for the range unless `--date-range` was supplied.
  Accepted values are `24h`/`past_24_hours` and `week`/`past_week`. A
  non-interactive run (tests, piped output, LangGraph Studio) keeps **Past 24
  hours** as the default.
- Task 1 has logged in and searched, and can apply either **Easy Apply** and
  **Past 24 hours** (`f_TPR=r86400`) or **Easy Apply** and **Past week**
  (`f_TPR=r604800`).
- Task 6 skips **Applied** cards and Task 7 paginates every results page.
- Task 13's Date posted module can select a range through the visible filter UI
  (pill → range radio → **Show results**) and verify it from `f_TPR`.
- The Date posted popover offers **Past week** (`f_TPR=r604800`) and **Past
  month** (`f_TPR=r2592000`). This task only uses the 24-hour and week ranges.

**Inputs**
- The startup choice: `past_24_hours` or `past_week`.
- The date range the current results list is filtered by (URL `f_TPR` and/or the
  checked Date posted option).
- The results-list cards and their **Applied** / **Easy Apply** state.
- The current pagination state and `_MAX_RESULT_PAGES`.
- The **Date posted** pill, both range options, and **Show results**.
- The **Easy Apply** filter state after the range reload.

**Steps**
1. Resolve the startup range:
   - `--date-range` on the CLI, or
   - the interactive startup prompt, or
   - the default **Past 24 hours** when stdin is not interactive.
   Normalize the answer to `past_24_hours` or `past_week`.
2. Apply exactly that range in Task 1. Verify it from the URL:
   `f_TPR=r86400` for Past 24 hours, `f_TPR=r604800` for Past week. Keep
   **Easy Apply** active; re-apply it through `f_AL=true` if the range reload
   dropped it.
3. Scan the chosen range exactly as Tasks 6-7 do: skip **Applied** cards, open
   the first unapplied **Easy Apply** job, and paginate while pages remain.
4. Only when the chosen range is genuinely exhausted — a page has no results, the
   pager reports **no next page**, or the pager controls are absent (single
   page) — and no job was selected, switch to the other range:
   - find the **Date posted** pill at runtime, open it, select the other range,
     and click **Show results** when present;
   - verify the results URL carries the target `f_TPR` (`r604800` for week,
     `r86400` for 24 hours); if the layout has no usable dropdown, add/replace
     `f_TPR` in the current URL while preserving every other parameter
     (`keywords`, `f_AL=true`, …);
   - reset the results pagination (`start`) so the fallback scan begins at page 1;
   - re-check the **Easy Apply** filter because the range reload can reset it,
     and re-apply it through `f_AL=true` (which preserves `f_TPR`).
5. Restart the Task 6/7 page scan on the fallback results from page 1, carrying
   over the already-tried job keys and the applied-job set so jobs already seen
   in the primary range are not reopened or double-counted.
6. Stop paginating the fallback range at its last page, at the per-range safety
   cap, or as soon as a job is selected. A later pass whose current range is
   already the fallback keeps scanning only that range; it does not bounce back
   to the primary range. Never switch to **Past month**.
7. Record the outcome on `Task2Outcome`:
   - `date_range_preferred` — the startup choice;
   - `date_range_used` — `"past_24_hours"` or `"past_week"` (the range the scan
     ended on);
   - `date_range_fallback_used` — true when the range was switched;
   - `pages_visited_past_week` — week pages scanned;
   - `pages_visited` — total pages across both ranges;
   - a clear note when both ranges were exhausted.
8. When the fallback range is also exhausted, stop cleanly. Task 8's stop reason
   names both ranges in the order the user chose them, rather than the misleading
   "every job on every results page is already Applied".
9. Continue the existing flow (Task 3 match, the human submit gate, Task 8's
   next-job loop). The selected range is also carried into self-healing browser
   reopens so a repaired run does not silently revert to Past 24 hours.

**Acceptance criteria**
- At startup the agent asks whether to search **Past 24 hours** or **Past week**
  first; `--date-range` supplies the answer non-interactively and a non-interactive
  run defaults to **Past 24 hours**.
- Task 1 applies the chosen range and verifies the matching `f_TPR` value.
- A chosen **Past 24 hours** list that is fully scanned with no selectable job
  switches to **Past week** and scans page 1 and subsequent pages automatically.
- A chosen **Past week** list that is fully scanned with no selectable job
  switches to **Past 24 hours** the same way.
- The switch is verified by the target `f_TPR`, not just a checked radio; the URL
  fallback preserves `f_AL=true` and every other query parameter and resets the
  page offset.
- Easy Apply stays selected after the range reload; it is re-applied through the
  URL when the reload dropped it.
- Jobs already tried/applied in the primary range are skipped in the fallback
  range (no duplicate popup, open, or fill), while older unapplied Easy Apply jobs
  are selected normally.
- A later scan already on the fallback range stays there instead of rescanning
  the primary range.
- The page scan is bounded per range (`_MAX_RESULT_PAGES`) and stops cleanly when
  the fallback range ends. Fallback is **not** attempted after the safety cap or
  after a recoverable pagination failure (the current range is not complete).
- `Task2Outcome` reports the preferred range, the used range, the fallback flag,
  and the week/total page counts; the CLI log/summary and Task 8's stop reason
  explain the fallback.
- Unit tests cover range detection, alias/startup-choice parsing, week selection
  (UI and URL fallback), pagination reset, both fallback directions, no fallback
  on cap/failure, no bounce-back, and no re-open of tried jobs. Live-browser
  fixture tests drive the real `_task1_on_page`/`_task2_on_page` paths and prove
  both 24 hours → week and week → 24 hours switches select the older job without
  clicking **Submit application**.
- Never click **Submit application**; submission remains a manual human step.

**Notes**
- **Do not confuse ranges.** `f_TPR=r86400` = Past 24 hours, `r604800` = Past
  week, `r2592000` = Past month. Only the 24-hour and week ranges are used.
- **Runtime discovery.** Discover the Date posted pill, the range radios, and
  **Show results** from their labels/roles; never use a fixed index or class.
- **One navigation at a time.** Wait for the range reload to settle before
  reading cards or re-checking Easy Apply.
- **No duplicate work.** The week list contains the 24-hour jobs. Carry the
  `tried` keys and `applied_seen` set into the fallback scan; do not clear Task
  16's accumulated skip titles either.
- **No month fallback.** Past month is explicitly out of scope for this task.
- **File-size limit.** `src/tools/linkedin_date_posted.py` was split into the
  `src/tools/linkedin_date_posted/` package in the original implementation. The
  startup/range helpers live in `src/date_range.py` and
  `src/date_range_choice.py`; the fallback and results-page walk stay in
  `src/tools/linkedin_date_range_fallback.py` and
  `src/tools/linkedin_results_scan.py`. No file crosses the 415-line limit.
- **Interrelated updates:** `src/state.py` (`date_range`,
  `date_range_preferred`), `src/nodes/ingest.py`, `src/nodes/browse.py`,
  `src/nodes/apply_loop.py`, `src/nodes/verify.py`,
  `src/tools/linkedin_job_selection.py`,
  `src/tools/linkedin_apply_loop.py`,
  `src/tools/self_healing/models.py`,
  `src/tools/self_healing/recovery.py`, `src/main.py`, `README.md`, and their
  tests.
- **Tests:** `tests/unit/test_task17_date_range_fallback.py`,
  `tests/unit/test_date_range_choice.py`,
  `tests/integration/test_date_posted_live.py`, and
  `tests/integration/test_task17_past_week_live.py`.
- **Live verification required:** run the fixtures in a real Chromium and confirm
  the selected range is applied, the fallback direction is correct, the page
  starts at page 1, Easy Apply remains selected, and the older unapplied job is
  selected. Run the unit suite and lint. Stop before any submit click.
- **Bug log:** if implementation exposes a new bug, add
  `known Bugs/task_17_bugs.md` and its row in `known Bugs/bug_log.md` with the
  symptom, root cause, fix, status, and evidence, as required by `AGENTS.md`.
- Never click **Submit application**; submission remains a manual human step.

**Implementation record (2026-10-28)**

- Added the shared range model in `src/date_range.py`:
  normalized range names, labels, `f_TPR` values, aliases, and the
  `other_date_range()` 24 hours ⇄ week mapping.
- Added the startup prompt in `src/date_range_choice.py`. The CLI exposes
  `--date-range {24h,week}`; an omitted value prompts only on an interactive
  stdin, otherwise it defaults to Past 24 hours.
- `src/main.py`, `src/state.py`, and `src/nodes/ingest.py` validate and carry the
  chosen range through the graph.
- `src/tools/linkedin_search/orchestrator.py` selects the chosen range in Task 1
  and verifies the matching `f_TPR`.
- `src/tools/linkedin_date_posted/selection.py` gained the generic
  `select_date_range_value()`; `src/tools/linkedin_date_range_fallback.py` now
  has `switch_to_date_range()` (with `switch_to_past_week()` kept as a
  compatibility wrapper).
- `src/tools/linkedin_results_scan.py` scans the preferred range and then the
  other range, records `date_range_preferred`/`date_range_used`, and stays on the
  fallback range on later passes instead of bouncing back.
- `src/nodes/browse.py`, `src/nodes/apply_loop.py`,
  `src/tools/linkedin_job_selection.py`, and
  `src/tools/linkedin_apply_loop.py` pass the preferred range through every scan.
- Self-healing carries the range in `JobTarget` and reopens the same job with the
  user's selected range.
- Updated `README.md` and added/updated unit and live-browser tests.

Verification performed:

```text
pytest tests/unit -q                                      # passed
ruff check src tests                                      # passed
AUTOJOB_TASK17_LIVE=1 AUTOJOB_TASK13_LIVE=1 \
  pytest tests/integration/test_task17_past_week_live.py \
         tests/integration/test_date_posted_live.py -q     # 5 passed
```

The live Chromium fixtures covered 24 hours → week, week → 24 hours, and Task 1
selecting the requested week range. No test or fixture clicked **Submit
application**. Changes are in the working tree; nothing was committed or pushed.
