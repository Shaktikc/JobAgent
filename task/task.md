# Tasks

## Task 1 — Log in to LinkedIn, search "software engineer", select Easy Apply

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
