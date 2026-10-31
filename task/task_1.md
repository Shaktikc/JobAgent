# Task 1 — Log in to LinkedIn, search the chosen job query, select Easy Apply

**Status:** ✅ Done

**Goal:** Launch the browser, open the LinkedIn login page, wait for the user to
log in successfully, search for the **job query resolved at startup** (Task 18),
and select the **Easy Apply** filter. The default query is
**"software engineer"** when none was supplied.

**Inputs**
- `url` — `https://www.linkedin.com/login/`
- `search_query` — the job query resolved by Task 18: `--query` when supplied,
  otherwise the startup answer, otherwise `software engineer`

**Steps**
1. Open the browser session.
2. Navigate to `https://www.linkedin.com/login/`.
3. Check whether the user is logged in.
4. **If NOT logged in:** wait for the user to log in (do not proceed until login
   is successful). Then continue to step 5.
5. **If logged in:** proceed directly to step 6.
6. Confirm login succeeded (e.g. the LinkedIn feed/home page is visible).
7. Type the resolved `search_query` (default "software engineer") into the jobs
   search bar and submit it. Searching follows LinkedIn's normal behavior and
   may reload or navigate the page.
8. After the search returns results, click the **"Try AI job Search"** button
   **if it is present** (it is optional); when it is absent, continue unchanged.
9. After clicking **"Try AI job Search"**, **repeat the job search** (type the
   resolved `search_query` into the search bar and submit again). 
10. Select the **Easy Apply** filter.

**Acceptance criteria**
- Browser opens successfully.
- LinkedIn login page loads.
- User logs in successfully.
- The **resolved job query** is typed into the jobs search bar and the search
  returns job results. With no `--query` and no interactive answer, that query
  is **"software engineer"**.
- The **"Try AI job Search"** button is clicked when present, and the same
  search is performed **again** after each click while the
  button reappears (capped); absence of the button does not fail the run and then
  the search is performed only once.
- The **Easy Apply** filter is selected.

**Notes**
- **Evolved by Task 18:** the query is no longer a hard-coded value. Task 1
  receives the resolved `search_query` and must search that value everywhere
  (search bar, repeated search, and the results URL). `"software engineer"`
  remains only the default when the human supplies nothing.
