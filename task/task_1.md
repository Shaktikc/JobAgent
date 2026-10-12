# Task 1 — Log in to LinkedIn, search "software engineer", select Easy Apply

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
7. Type "software engineer" into the jobs search bar and submit it. Searching
   follows LinkedIn's normal behavior and may reload or navigate the page.
8. After the search returns results, click the **"Try AI job Search"** button
   **if it is present** (it is optional); when it is absent, continue unchanged.
9. After clicking **"Try AI job Search"**, **repeat the job search** (type
   "software engineer" into the search bar and submit again). 
10. Select the **Easy Apply** filter.

**Acceptance criteria**
- Browser opens successfully.
- LinkedIn login page loads.
- User logs in successfully.
- **"software engineer"** is typed into the jobs search bar and the search
  returns job results.
- The **"Try AI job Search"** button is clicked when present, and the
  "software engineer" search is performed **again** after each click while the
  button reappears (capped); absence of the button does not fail the run and then
  the search is performed only once.
- The **Easy Apply** filter is selected.
