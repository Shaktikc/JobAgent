# Tasks

## Task 1 — Log in to LinkedIn, search "software engineer", select Easy Apply

**Status:** ✅ Done

**Goal:** Launch the browser, open the LinkedIn login page, wait for the user to
log in successfully, search for **"software engineer"** jobs, and select the
**Easy Apply** filter.

**Inputs**
- `url` — `https://www.linkedin.com/login/`
- `search_query` — `software engineer`

**Steps**
1. Open the browser session.
2. Navigate to `https://www.linkedin.com/login/`.
3. Check whether the user is logged in.
4. **If NOT logged in:** wait for the user to log in (do not proceed until login
   is successful). Then continue to step 5.
5. **If logged in:** proceed directly to step 6.
6. Confirm login succeeded (e.g. the LinkedIn feed/home page is visible).
7. Open the jobs search tab and **type "software engineer" into the search bar**,
   then submit the search.
8. Open the search results and select the **Easy Apply** filter.

**Acceptance criteria**
- Browser opens successfully.
- LinkedIn login page loads.
- User logs in successfully.
- **"software engineer"** is typed into the jobs search bar and the search
  returns job results.
- The **Easy Apply** filter is selected.

**Notes**
- Browser automation is opt-in (`AUTOJOB_*` settings, `--dry-run` off).
- The query must be entered through the jobs search bar (typed in), not by
  navigating to a search URL.
- **Login gate:** if the user is not logged in, pause and wait for the user to
  log in. Only once login is successful do the remaining steps (search
  "software engineer" → select Easy Apply).
- If the search or filter is not found, capture a screenshot and the page URL for debugging.

---

## Task 2 — Select Easy Apply from the job list

**Status:** ✅ Done

**Goal:** From the list of jobs seen after Task 1, select a job's **Easy Apply**
button.

**Preconditions**
- Task 1 is complete: user is logged in, "software engineer" jobs are shown, and
  the **Easy Apply** filter is selected.

**Inputs**
- None (uses the job list from Task 1).

**Steps**
1. Read the list of jobs currently displayed in the search results.
2. Pick a job from the list (the first / next unprocessed one).
3. Locate that job's **Easy Apply** button.
4. Click the **Easy Apply** button.
5. Confirm the Easy Apply flow/application form opened.

**Acceptance criteria**
- A job from the list is selected.
- The **Easy Apply** button is found and clicked.
- The Easy Apply application form/modal is visible after the click.

**Notes**
- If a job has no **Easy Apply** button, skip it and move to the next job.
- If the button is not found, capture a screenshot and the page URL for debugging.
