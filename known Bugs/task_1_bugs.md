# Task 1 — Bugs (login, search, Easy Apply filter)

Bugs whose root cause is in **Task 1**: logging in, running the LinkedIn job
search (including the optional "Try AI job search" detour), and selecting the
**Easy Apply** filter.

See [`bug_log.md`](bug_log.md) for the master index and the entry format.
Status: 🟢 Fixed · 🟡 Fixed (superseded) · 🔴 Open · ⚪ Won't fix

| ID | Symptom (short) | Status | Fix commit(s) |
|----|-----------------|--------|---------------|
| BUG-011 | "Try AI job search" button not clicked (markup/label) | 🟢 Fixed | `1dbb380`, `2dd5005`, `e5a7c7d` |
| BUG-012 | click navigated/reloaded, `Element.click()` looked failed | 🟢 Fixed | `4eee839`, `1dbb380` |
| BUG-013 | "many buttons clicked at once" on a half-loaded page | 🟢 Fixed | `48b4eb6` |
| BUG-014 | AI detour left zero job cards (semantic mode) | 🟡 Fixed (superseded) | `888e11d` → `9270f3a` |
| BUG-015 | "no page reload" rule was wrong | 🟡 Fixed (superseded) | `9270f3a` |
| BUG-016 | Easy Apply **filter** confused with the blue apply button | 🟢 Fixed | (Task 1 filter fix) |

---

### BUG-011 — the "Try AI job search" button was not clicked

- **Symptom:** a real run showed the optional **"Try AI job search"** control was
  never clicked, so the intended AI detour did not happen.
- **Root cause:** discovery used a fixed `<button>` selector and a single visible
  label, so link/role-based markup or a different accessible name was missed.
- **Fix:** discover controls at runtime (a JS scan of `button`, `a`, `[role=button]`,
  `[role=link]`, `[role=tab]`, button inputs); combine `aria-label`, `title`,
  visible text, and `value`; match any label with an `AI` token that also mentions
  "search" while excluding "Save this search" / "AI resume builder"; poll briefly
  after results load; record candidates for diagnostics when nothing matches.
- **Evidence:** `src/tools/browser.py` (`_AI_CANDIDATES_QUERY`,
  `find_ai_job_search_button`, `click_ai_job_search`),
  `src/tools/linkedin.py` (`looks_like_ai_job_search`),
  `tests/integration/test_task1_ai_search_live.py`. Commits
  `1dbb380`, `2dd5005`, `e5a7c7d`.

### BUG-012 — clicking AI search navigates, so the click looked failed

- **Symptom:** the repeat search after a successful AI click never ran; the click
  was treated as failed.
- **Root cause:** clicking **"Try AI job search"** navigates/reloads the page, so
  `Element.click()` can raise after the navigation already started (the CDP
  execution context is destroyed).
- **Fix:** treat a changed URL as a successful click, and await the page load after
  the click before repeating the search.
- **Evidence:** `src/tools/browser.py`; `tests/integration/test_task1_ai_search_live.py`.
  Commits `4eee839`, `1dbb380`.

### BUG-013 — several controls clicked at once on a half-loaded page

- **Symptom:** the flow appeared to click several controls at once.
- **Root cause:** after a click that navigates/reloads, the next step interacted
  with a half-loaded page.
- **Fix:** `_settle_after_click` — after a click, pause
  `post_click_wait_seconds` and wait for `document.readyState === 'complete'`
  before touching the next control. (Submitting the search and the filter click
  both settle now.)
- **Evidence:** `src/tools/linkedin_search.py`; regression test
  `test_type_jobs_search_waits_for_the_page_to_load_after_submitting`. Commit
  `48b4eb6`.

### BUG-014 — the optional AI detour left no job list

- **Symptom:** after **"Try AI job search"**, LinkedIn switched to
  `.../jobs/search-results/?origin=SEMANTIC_SEARCH_MODE_FROM_CLASSIC` with no
  `keywords` and rendered **zero** job cards, so Task 2 found `0 job(s)` and the
  run failed.
- **Root cause:** an *optional* control could remove the job list the run depends
  on.
- **Fix:** first added `restore_job_search` to navigate to the standard jobs search
  URL when the post-AI repeat search found nothing.
- **Status:** 🟡 **Fixed (superseded)** — `9270f3a` removed `restore_job_search` after
  BUG-015 re-established normal navigation.
- **Evidence:** `src/tools/browser.py` (`restore_job_search`);
  `test_run_task1_recovers_when_the_ai_search_leaves_no_jobs`. Commit `888e11d`
  then `9270f3a`.

### BUG-015 — the "no page reload" rule was itself wrong

- **Symptom:** a fix that forced Task 1 searches to avoid navigation was fighting
  LinkedIn's normal behaviour.
- **Root cause:** submitting the jobs search *does* reload/navigate the page in
  LinkedIn's normal flow.
- **Fix:** drop the `open_jobs_tab` / `allow_navigation` options; let searches
  follow normal navigation, and remove the now-unneeded `restore_job_search`.
- **Status:** 🟡 **Fixed (superseded by design change)**; it corrected BUG-014's
  premise.
- **Evidence:** `src/tools/browser.py`, `task/task_1` spec, unit + live tests.
  Commit `9270f3a`.

### BUG-016 — the Easy Apply filter was confused with the blue apply button

- **Symptom (from a screenshot):** the results page shows a filter pill
  (`role="radio"`, `aria-checked`, `id searchFilter_applyWithLinkedin`) and two
  blue `jobs-apply-button` controls, all mentioning "Easy Apply"; the wrong one
  could be selected.
- **Root cause:** label-only matching could not tell the filter toggle from the
  per-job apply button.
- **Fix:** `find_easy_apply_filter` skips `jobs-apply-button` controls and prefers
  the filter pill / toggle attributes.
- **Evidence:** `src/tools/browser.py`;
  `test_find_easy_apply_filter_from_real_linkedin_dom`,
  `test_find_easy_apply_filter_never_returns_the_apply_button`,
  `test_find_easy_apply_filter_skips_apply_button_by_class`.
