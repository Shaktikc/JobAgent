# Task 7 — When every job on the page is "Applied", go to the next results page

**Status:** ✅ Done

**Goal:** When **every** job on the current results page is already marked
**"Applied"** (Task 7 found no unapplied job), move to the **next results page**
using the pagination controls and keep looking, until an unapplied job is found
or there are no more pages.

**Preconditions**
- Task 7 is complete on the current page: every card is Applied and no job was
  opened.
- The results list is paginated (page numbers `1 2 3 …` with a **Next** button
  below the list).

**Inputs**
- The results pagination controls (page numbers and the **Next** / **Previous**
  buttons) below the job list.
- The current page number (to detect that the page actually advanced).

**Steps**
1. On the results page where Task 7 found every card Applied, locate the
   pagination controls below the job list.
2. Determine whether there is a next page: the **Next** button is enabled, or a
   higher page number exists.
3. If a next page exists, click **Next** (or the next page number) and wait for
   the new page of job cards to load.
4. Re-run Task 7's logic on the new page: skip the Applied cards and open the
   first unapplied job.
5. Repeat steps 1–4 for each subsequent page: only paginate again when the whole
   page is Applied.
6. Stop paginating when:
   - an unapplied job is opened (Task 7 resumes normally), or
   - the **Next** button is disabled/absent (last page), or
   - the page number no longer changes after a click (pagination is stuck), or
   - the safety cap of visited pages is reached.
7. If every job on every page is Applied, stop gracefully with a clear note that
   no unapplied jobs were found across the pages searched, and open nothing.

**Acceptance criteria**
- When every card on the current page is Applied, the next results page is
  opened automatically.
- After paginating, Task 7's skip logic runs again on the new page's cards.
- Pagination stops at the last page (Next disabled/absent), when pagination is
  stuck, or after the safety cap.
- The number of pages visited is recorded in the outcome/log.
- If all jobs on all pages are Applied, the run stops with a clear note and opens
  nothing.
- Going to the next page never opens or applies to a job by itself.

**Notes**
- **Pagination is dynamic:** discover the controls at runtime rather than
  assuming a selector. The list shows page numbers plus **Next** (and often
  **Previous**).
- Detect "last page" by the **Next** control being disabled, absent, or by the
  page number/content not changing after a click.
- Advancing a page must **not** be mistaken for opening a job: after paginating,
  re-read the cards and re-check their statuses instead of carrying over the
  previous page's decision.
- Cap pagination (e.g. `_MAX_RESULT_PAGES`) so a control that never disables can
  never loop forever, consistent with the existing click caps.
- Record the number of results pages visited (e.g. `pages_visited`) on
  `Task2Outcome` for the log/summary.
- If the pagination controls cannot be found, stop gracefully with a clear note
  instead of retrying blindly.
- Never click Submit; submission stays a manual human step.
