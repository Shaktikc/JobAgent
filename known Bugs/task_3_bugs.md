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
| BUG-038 | resume match hung for minutes / "unusable match reply" | 🟢 Fixed | (uncommitted) |
| BUG-039 | job title read as "0 notifications" → weak resume match | 🟢 Fixed | (uncommitted) |

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

### BUG-038 — the resume match hung on the LLM call, or failed as "unusable"

- **Symptom:** a run stopped at `LLM: choosing the best-matching resume ...` for
  minutes, or failed with `the LLM returned an unusable match reply`; a cold run
  also re-described every resume one after another.
- **Root cause:** the configured model is a reasoning model. Each match call spent
  700–2,600 hidden reasoning tokens (6–17 s for a realistic job description), and
  every stale resume was described **sequentially**. Under load that reached the
  60 s client timeout, which the SDK retried 3× — up to four minutes on the same
  line. When reasoning consumed the output budget the API returned
  `finish_reason=length` with **empty** `content`, which the code reported as an
  unusable reply. The JSON extractor also used a greedy `\{.*\}` regex, so any
  brace-delimited text around the answer made parsing fail.
- **Fix:** Task 3.2's structured calls now request JSON mode and disable OpenRouter
  reasoning (`reasoning: {enabled: false}`, `AUTOJOB_LLM_DISABLE_REASONING`,
  default true), dropping either knob if an endpoint rejects it. An empty or
  unusable reply is retried once with a JSON-only nudge. The parser scans balanced
  JSON objects and prefers the final object containing the expected keys. Resume
  descriptions now run concurrently (bounded at 4) and the store is written once.
  Status lines report each call's elapsed time.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/resume_descriptions/` (`client.py`, `messages.py`,
  `store.py`), `src/tools/linkedin_best_matching_resume/selection.py`,
  `src/configuration.py`; `tests/unit/test_resume_descriptions.py`
  (`test_parse_match_finds_the_answer_after_an_example_object`,
  `test_pick_best_resume_requests_json_and_no_reasoning`,
  `test_pick_best_resume_retries_an_empty_reply`,
  `test_describe_resume_retries_an_unusable_reply`),
  `tests/unit/test_configuration.py`. Live check with the real LLM: warm match
  **1.3–1.4 s** (was 6–17 s), cold four-resume pool **10–12 s** (was four
  sequential calls plus the match). Commit: (uncommitted).

### BUG-039 — the job title was read as LinkedIn's "0 notifications"

- **Symptom:** a Full Stack Engineer job was logged and matched as
  `'0 notifications'`; the resume match then ran on a meaningless title.
- **Root cause:** the description query's title fallback searched the **whole
  document** with generic `h1`/`h2` selectors. On the AI/semantic job view (hashed
  classes) the job-specific title selectors can be absent; the generic `h1`/`h2`
  fallback then returned the global navigation heading `0 notifications` before
  the page title was considered.
- **Fix:** the title, company, location, and body lookups are scoped to the
  job-details pane first; nav strings and `(N) notifications` are rejected; the
  page title is tried before any global fallback, and generic headings are only
  read inside the pane.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_best_matching_resume/description_reader.py`;
  `tests/integration/test_job_description_live.py` (`global-nav` case). Live run
  with the real Chromium query: 4 cases passed. Commit: (uncommitted).
