# Task 13 — Select the Date posted filter to "Past 24 hours"

**Status:** ⬜ Not started

**Goal:** On the LinkedIn jobs results page opened by Task 1, open the
**Date posted** filter, select **"Past 24 hours"**, apply it with **Show
results**, and verify the results are limited to jobs posted in the last 24
hours. The date filter must be combined with the existing **Easy Apply** filter,
and the run must continue to Task 2 on the filtered results list. The agent
never submits an application.

**Preconditions**
- Task 1 has logged in and searched for the configured query (default
  `"software engineer"`), and the results page is visible.
- The results page exposes the **Date posted** filter (a button/pill that opens
  a dropdown or popover). This is the classic jobs results layout shown in the
  Task 13 reference screenshot.
- The **Easy Apply** filter is selected (or can be re-selected after the date
  filter reloads the page).
- Task 2 still runs after this task and opens the first matching Easy Apply job.

**Inputs**
- The results page's **Date posted** button/pill.
- The dropdown/popover options: **Past month**, **Past week**, and **Past 24
  hours**.
- The popover's **Show results** button (or the equivalent apply control, when
  the layout applies the selection immediately).
- The current results URL and the existing Easy Apply filter state.

**Steps**
1. After the search results load and the Easy Apply filter is selected, locate
   the **Date posted** filter by its visible text/accessible label on the
   results page. Do not match a job card's "Posted 1 day ago" text or any other
   control that merely contains the word "posted".
2. Scroll the **Date posted** control into view and click it to open the filter
   dropdown. Wait for the popover to render.
3. Inside the open popover, find the option whose normalized text is
   **"Past 24 hours"** (case-insensitive, whitespace-collapsed). It is normally a
   radio control. Select it by clicking the option or its radio/input.
4. Click **Show results** in the popover to apply the selection. If the layout
   has no separate **Show results** control, continue once the selected option's
   state is visibly applied.
5. Wait for the results page to reload/settle before interacting with anything
   else. A filter click may navigate or re-render the page.
6. Verify the filter is active using at least one authoritative signal:
   - the **Past 24 hours** option/radio is checked (for example
     `aria-checked="true"`), and/or
   - the results URL contains **`f_TPR=r86400`**, which is LinkedIn's
     **Past 24 hours** range parameter.
   The visible **Date posted** button may keep its generic label or show the
   selected range; either is acceptable when one of the signals above proves the
   selection.
7. Re-check the **Easy Apply** filter after the date filter is applied. Applying a
   filter reloads the page and can reset the other pill. If Easy Apply is no
   longer selected, select it again and verify it (`f_AL=true` or its
   `aria-checked`/`aria-pressed` state).
8. Record the result on the Task 1 outcome, for example
   `date_posted_filter_selected=True` and
   `date_posted_filter_value="past_24_hours"`, plus a short note. On failure,
   record the page URL, the controls/options that were actually seen, and a
   screenshot under `data/debug/`.
9. Continue the existing flow to Task 2 on the filtered results list. Do not
   open a job or click **Submit application** from this task.

**Acceptance criteria**
- The **Date posted** filter is found on the results page using runtime
  discovery (not a hard-coded position).
- **"Past 24 hours"** is selected, and **Show results** is used when the layout
  provides it.
- The selection is verified by a checked **Past 24 hours** option and/or
  `f_TPR=r86400` in the results URL. Being on the unfiltered default page is not
  success.
- The **Easy Apply** filter remains selected together with the date filter after
  the results reload.
- Task 1 reports the date filter as selected, and a failed selection fails the
  task with a clear note instead of silently continuing on unfiltered results.
- The run continues to Task 2 with the combined filters, and no application is
  submitted by this task.

**Notes**
- **The filter is dynamic.** Discover the button, options, and apply control at
  runtime from their labels and roles; never assume a fixed index or CSS class.
  The button's label may change after selection, so accept both
  `"Date posted"` and a selected-range label such as `"Past 24 hours"`.
- **Do not confuse ranges.** LinkedIn uses `f_TPR=r86400` for **Past 24 hours**,
  `f_TPR=r604800` for **Past week**, and `f_TPR=r2592000` for **Past month**.
  Only `r86400` satisfies this task.
- **Prefer the visible UI path.** If the dropdown or **Show results** control is
  unavailable on a LinkedIn layout (for example the AI/semantic results page),
  fall back to adding `f_TPR=r86400` to the current results URL while preserving
  the existing query parameters (`keywords`, `f_AL=true`, and any others), then
  verify the parameter and the loaded results. Record that the URL fallback was
  used.
- **One navigation at a time.** A filter click can reload the page; wait for the
  post-click settle (`post_click_wait_seconds` / page load) before reading or
  clicking the next control.
- **Preserve the existing filters.** Never drop the Easy Apply selection when
  applying the date filter. If the page resets it, re-apply it before Task 2.
- **Outcome and reporting (interrelated updates):** add
  `date_posted_filter_selected` and `date_posted_filter_value` to
  `Task1Outcome`; include them in `_task1_ok`, `browse`'s log/errors, Task 11's
  Task 1 recovery check, the CLI summary, `verify`, and the README/behaviour
  notes. Existing callers and tests that omit the new fields must keep working
  (default `False` / `""`), but a real Task 1 run must require the date filter.
- **Proposed new module (needs human approval before creating):**
  `src/tools/linkedin_date_posted.py`, containing the pure label/range helpers
  and the deterministic browser steps (`find_date_posted_filter`,
  `select_past_24_hours`, `date_posted_filter_selected`). Keep
  `src/tools/linkedin_search.py` as the Task 1 orchestrator and call the new
  module from it. If the module would exceed the 415-line limit, split it into a
  package with a thin `__init__.py` re-exporting the public API.
- **Tests:** add unit tests for label/range normalization and for the
  click → select **Past 24 hours** → **Show results** → verify path using fake
  elements, including the failure case where the option is absent or the page
  stays unfiltered. Add/extend a live-browser test that serves a LinkedIn-shaped
  results page and verifies the real interaction, plus the existing live Task 1
  check on the real site. Do not mark the task done from unit tests alone.
- **Live verification required:** run the real flow and confirm in the browser
  that the **Date posted** dropdown shows **Past 24 hours** selected, the
  results reload with the 24-hour range (`f_TPR=r86400`), and **Easy Apply**
  remains selected before Task 2 opens a job.
- **Bug log:** if implementation exposes a new bug, record it in the appropriate
  `known Bugs/task_13_bugs.md` (ask for approval before creating the file) and in
  `known Bugs/bug_log.md`, as required by `AGENTS.md`.
- Never click **Submit application**; submission remains a manual human step.
