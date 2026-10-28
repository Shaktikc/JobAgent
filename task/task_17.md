# Task 17 — Fall back to "Past week" when the Past 24 hours results are exhausted

**Status:** ✅ Done

**Goal:** When every job on every **Past 24 hours** results page has been scanned
and no openable (unapplied, Easy Apply) job is left, widen the **Date posted**
filter to **Past week** and keep scanning instead of stopping. The week range
includes the 24-hour jobs already scanned, so the same applied/skipped jobs are
never opened again; only the older jobs become new candidates. The run stops
cleanly after the week range is also exhausted. The agent **never** clicks
**Submit application**.

**Preconditions**
- Task 1 has logged in, searched, and applied **Easy Apply** and **Date posted →
  Past 24 hours**; the results URL carries `f_AL=true` and `f_TPR=r86400`.
- Task 6 skips **Applied** cards and Task 7 paginates every results page.
- Task 13's Date posted module can select a range through the visible filter UI
  (pill → range radio → **Show results**) and verify it from `f_TPR`.
- The Date posted popover offers **Past week** (`f_TPR=r604800`) and **Past
  month** (`f_TPR=r2592000`). This task only widens to **Past week**.

**Inputs**
- The date range the current results list is filtered by (URL `f_TPR` and/or the
  checked Date posted option).
- The results-list cards and their **Applied** / **Easy Apply** state.
- The current pagination state and `_MAX_RESULT_PAGES`.
- The **Date posted** pill, its **Past week** option, and **Show results**.
- The **Easy Apply** filter state after the range reload.

**Steps**
1. Detect the current date range before scanning. `f_TPR=r604800` (or a checked
   **Past week** option) means the list is already on the week range; keep
   scanning it as today. `f_TPR=r86400` (or a checked **Past 24 hours** option)
   means begin with the 24-hour range.
2. Scan the current range exactly as Tasks 6-7 do: skip **Applied** cards, open
   the first unapplied **Easy Apply** job, and paginate while pages remain.
3. Only when the range is genuinely exhausted — a page has no results, the pager
   reports **no next page**, or the pager controls are absent (single page) —
   and no job was selected, switch to **Past week**:
   - find the **Date posted** pill at runtime, open it, select **Past week**,
     and click **Show results** when present;
   - verify the results URL now carries `f_TPR=r604800`; if the layout has no
     usable dropdown, add/replace `f_TPR=r604800` in the current URL while
     preserving every other parameter (`keywords`, `f_AL=true`, …);
   - reset the results pagination (`start`) so the week scan begins at page 1;
   - re-check the **Easy Apply** filter, because the range reload can reset it,
     and re-apply it through `f_AL=true` (which preserves `f_TPR`).
4. Restart Task 6/7's page scan on the week results from page 1, carrying over
   the already-tried job keys and the applied-job set so the 24-hour jobs that
   also appear in the week list are not reopened or double-counted.
5. Stop paginating the week range at its last page, at the per-range safety cap,
   or as soon as a job is selected. Never switch to **Past month** in this task.
6. Record the outcome on `Task2Outcome`:
   - `date_range_used` — `"past_24_hours"` or `"past_week"`;
   - `date_range_fallback_used` — true when the range was widened;
   - `pages_visited_past_week` — week pages scanned;
   - `pages_visited` — total pages across both ranges;
   - a clear note when both ranges were exhausted.
7. When the week range is also exhausted, stop cleanly. Task 8's stop reason must
   say that no unapplied Easy Apply job remains in the past 24 hours or the past
   week, rather than the misleading "every job on every results page is already
   Applied" (the week list may contain unapplied jobs that the run skipped).
8. Continue the existing flow (Task 3 match, the human submit gate, Task 8's
   next-job loop). A later scan that is already on the week range keeps using
   the week range; it must not revert to 24 hours or widen to a month.

**Acceptance criteria**
- A 24-hour results list that is fully scanned with no selectable job switches
  to **Past week** and scans its first page and subsequent pages automatically.
- The switch is verified by `f_TPR=r604800`, not just a checked radio; the URL
  fallback preserves `f_AL=true` and every other query parameter and resets the
  page offset.
- Easy Apply stays selected after the range reload; it is re-applied through the
  URL when the reload dropped it.
- Jobs already tried/applied in the 24-hour range are skipped in the week range
  (no duplicate popup, open, or fill), while older unapplied Easy Apply jobs are
  selected normally.
- The page scan is bounded per range (`_MAX_RESULT_PAGES`) and stops cleanly
  when the week range ends. Fallback is **not** attempted after the safety cap
  or after a recoverable pagination failure (the 24-hour scan is not complete).
- `Task2Outcome` reports the used range, the fallback flag, and the week/total
  page counts; the CLI log/summary and Task 8's stop reason explain the fallback.
- Unit tests cover range detection, week selection (UI and URL fallback),
  pagination reset, fallback on clean exhaustion, no fallback on cap/failure,
  and no re-open of tried jobs. A live-browser fixture test drives the real
  `_task2_on_page` path against a LinkedIn-shaped page and proves a 24-hour→week
  switch selects the older job without clicking **Submit application**.
- Never click **Submit application**; submission remains a manual human step.

**Notes**
- **Do not confuse ranges.** `f_TPR=r86400` = Past 24 hours, `r604800` = Past
  week, `r2592000` = Past month. Only `r604800` satisfies this task.
- **Runtime discovery.** Discover the Date posted pill, the **Past week** radio,
  and **Show results** from their labels/roles; never use a fixed index or class.
- **One navigation at a time.** Wait for the range reload to settle before
  reading cards or re-checking Easy Apply.
- **No duplicate work.** The week list contains the 24-hour jobs. Carry the
  `tried` keys and `applied_seen` set into the week scan; do not clear Task 16's
  accumulated skip titles either.
- **No month fallback.** Past month is explicitly out of scope for this task.
- **File-size limit.** The existing `src/tools/linkedin_date_posted.py` is at the
  415-line limit, so split it into a `src/tools/linkedin_date_posted/` package
  with a thin `__init__.py` re-exporting its public API before adding the
  generic range helpers. Put the range fallback and the results-page walk in
  their own modules (`src/tools/linkedin_date_range_fallback.py`,
  `src/tools/linkedin_results_scan.py`) so no file grows past the limit.
- **Interrelated updates:** `src/state.py` (`Task2Outcome` fields),
  `src/tools/linkedin_job_selection.py` (thin Task 2 wrapper),
  `src/tools/linkedin_apply_loop.py` (`open_next_job` range pass-through and
  stop reason), `src/nodes/apply_loop.py` (pass the last used range),
  `src/nodes/browse.py` and `src/main.py` (log/summary), `README.md`, and their
  tests.
- **Tests:** add `tests/unit/test_task17_date_range_fallback.py` (range helpers,
  week selection, pagination reset, fallback/no-fallback decisions) and extend
  `tests/integration/test_date_posted_live.py` or add a focused live-browser
  fixture test for the real `_task2_on_page` switch.
- **Live verification required:** run the fixture in a real Chromium and confirm
  the filter changes to **Past week** (`f_TPR=r604800`), the page starts at page
  1, Easy Apply remains selected, and the older unapplied job is selected. Run
  the unit suite and lint. Stop before any submit click.
- **Bug log:** if implementation exposes a new bug, add
  `known Bugs/task_17_bugs.md` and its row in `known Bugs/bug_log.md` with the
  symptom, root cause, fix, status, and evidence, as required by `AGENTS.md`.
- Never click **Submit application**; submission remains a manual human step.
