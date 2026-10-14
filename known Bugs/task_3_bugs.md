# Task 3 — Bugs (read the job description, pick the resume)

Bugs whose root cause is in **Task 3**: reading the open job's description and
choosing the best-matching resume.

See [`bug_log.md`](bug_log.md) for the master index and the entry format.
Status: 🟢 Fixed · 🟡 Fixed (superseded) · 🔴 Open · ⚪ Won't fix

| ID | Symptom (short) | Status | Fix commit(s) |
|----|-----------------|--------|---------------|
| BUG-004 | `get_state_as_text` was dead after an agent run (page read) | 🟢 Fixed | `24d381f` |
| BUG-021 | description read *after* Easy Apply → empty → LLM "none" | 🟢 Fixed | `7dce47d` |
| BUG-031 | unread description treated as "no resume matched" | 🟢 Fixed | `7dce47d` |

---

### BUG-004 — `get_state_as_text` was dead after an agent run

- **Symptom:** `discover.read_job` could not read page text for the guard after
  an agent run.
- **Root cause:** `get_state_as_text` dies with the run's event handlers.
- **Fix:** read page text through `browser.read_page_text` (CDP).
- **Evidence:** `tests/unit/test_discover_read_job.py` (2). Commit `24d381f`.

### BUG-021 — description read *after* Easy Apply came back empty

- **Symptom:** the LLM answered "none" because the job description was empty.
- **Root cause:** on LinkedIn's newer inline Easy Apply form the job view can be
  replaced by the form, hiding the description.
- **Fix:** capture the description **before** the Easy Apply click (a `capture`
  callback in `_scan_page`), store it on `Task2Outcome.job_description`, and only
  re-read if the capture produced nothing. The Task 8 loop does the same.
- **Evidence:** `src/tools/linkedin_job_selection.py`,
  `src/tools/browser.py`, `src/tools/linkedin_apply_loop.py`;
  `test_task2_captures_the_description_before_easy_apply`,
  `tests/integration/test_job_description_live.py`. Commit `7dce47d`.

### BUG-031 — an unread description treated as "no resume matched"

- **Symptom:** a readable-looking "none" from the LLM when the description had
  not actually been read.
- **Root cause:** `match` treated an unread description as a normal no-match case,
  which would wrongly ask the human for a resume and poison the remembered-resume
  library with an empty job profile.
- **Fix:** `match` fails fast when `JobDescription.is_read` is false, with
  `"match: the job description could not be read"`.
- **Evidence:** `src/nodes/match.py`, `src/state.py`
  (`JobDescription.is_read`). Commit `7dce47d`.
