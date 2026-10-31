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
| BUG-038 | resume match hung for minutes / "unusable match reply" | 🟢 Fixed | `1ca5311` |
| BUG-039 | job title read as "0 notifications" → weak resume match | 🟢 Fixed | `1ca5311` |
| BUG-072 | AI/search view read the survey heading + job list as the job | 🟢 Fixed | `55a7838` |
| BUG-078 | a strong candidate was skipped when the LLM's single choice was partial | 🟢 Fixed | (uncommitted) |
| BUG-079 | profiles dropped leadership/platform/AI-tool evidence and were reused after prompt changes | 🟢 Fixed | (uncommitted) |

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
  sequential calls plus the match). Commit `1ca5311`.

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
  with the real Chromium query: 4 cases passed. Commit `1ca5311`.

### BUG-072 — the AI/search job view read a survey heading and the job list as the job

- **Symptom:** during Task 12's live verification the open job
  "Software Engineer - AI Legal Risk Systems" (LEAP Legal Software) was read as
  title `"Are these results helpful?"`, company `""`, and a 4,935-character body
  made up mostly of the job list and page chrome. Task 12's job context therefore
  had a wrong title/company and noisy evidence, and Task 3's resume match was
  based on the same text.
- **Root cause:** on LinkedIn's AI/search landing view the details pane has no
  stable class names. The reader fell back to `main`, tried a generic `h1`/`h2`
  **before** the tab title, and returned the survey heading that precedes the job
  description. The paragraph fallback then joined every `<p>`/`<li>` in `main`,
  including the results list and survey/footer text. The tab title itself was
  correct and contained both the job title and company.
- **Fix:** parse the tab title (`Job title | Company | LinkedIn`) into the title
  and company fallbacks, reject survey/chrome headings, prefer the tab title over
  generic pane headings, and read the body from the text after LinkedIn's
  "About the job" heading (cutting the Premium footer) before the whole-page
  paragraph fallback. Title/company/body selected from stable job selectors are
  unchanged.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/linkedin_best_matching_resume/description_reader.py`;
  `tests/integration/test_job_description_live.py` (`ai-search-survey` case,
  plus the existing four layouts). Live Chromium check against the real LinkedIn
  page: title `"Software Engineer - AI Legal Risk Systems"`, company
  `"LEAP Legal Software"`, body starts `"About LEAP …"` and contains
  `"Develop core features and APIs"`, with no survey/footer text. Commit
  `55a7838`.

### BUG-078 — a good resume was skipped when the LLM's single choice was only partial

- **Symptom:** intermittently, a job that clearly matched an existing resume was
  skipped as "no strong resume match" even though another resume in the pool
  satisfied the job. The gate trusted the LLM's single `choice`; if the model
  picked a thematically closer but weaker resume (for example an AI-titled resume
  at an AI company) and rated it `partial`, the job was skipped without
  considering that the model itself might rate a better resume `strong`.
  Reproduced deterministically in the parser with
  `choice=c1 partial` and `ratings={c1: partial, c4: strong}`.
- **Root cause:** the match reply only contained one chosen id and one fit. The
  strict Task 16 gate (`should_skip_job`) correctly treats a non-strong choice as
  a skip, but it had no per-candidate evidence to fall back to.
- **Fix:** ask the model to rate **every** candidate (best first) in `ratings`,
  parse both object and list shapes, ignore unknown ids, and accept qualified
  values such as `"strong fit"`. When the single choice is not strong, select
  another candidate the LLM rated `strong` (never overriding the chosen id's
  explicit rating) and record the override in the rationale. The decision remains
  100% LLM-driven; no keyword scoring was added.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/resume_descriptions/messages.py`,
  `src/tools/resume_descriptions/models.py`, `src/state.py`
  (`Task3Outcome.ratings`), `src/tools/linkedin_best_matching_resume/selection.py`,
  `src/nodes/match.py` (the run log now prints the rating map);
  `tests/unit/test_resume_descriptions/test_match.py`
  (`test_parse_match_uses_a_strong_rating_when_the_single_choice_is_partial`,
  `test_parse_match_accepts_a_list_of_ratings`,
  `test_parse_match_keeps_a_partial_choice_when_nothing_is_strong`,
  `test_parse_match_ignores_unknown_rating_ids`), and
  `tests/unit/test_task16_resume_gate.py` (ratings propagation). Live run against
  the real Applied Intelligence LinkedIn job: `fit=strong`. Commit (uncommitted).

### BUG-079 — resume profiles dropped senior evidence and were reused after prompt changes

- **Symptom:** senior/platform roles could be rated `partial` because the matcher
  only saw a one-line summary, skills, titles, seniority, years, and domain. The
  resume's leadership, architecture, platform/tooling work, and named AI coding
  tools were dropped, even when the job asked for them. Changing the profile
  prompt also had no effect on existing resumes: the store was considered fresh
  whenever the file's mtime and size matched, so old weak profiles were reused
  forever.
- **Root cause:** the description schema was lossy for responsibilities and the
  freshness check had no prompt/schema version.
- **Fix:** add `highlights` (up to 6 factual achievements/responsibilities,
  including leadership, architecture, platform/tooling, delivery, and production
  operations) and `ai_coding_tools` to the profile; include them in the match
  prompt; and tell the matcher that seniority may come from years/scope rather
  than the literal word "Senior". Add `PROFILE_VERSION = 2` to every stored entry
  and require it in `is_fresh`, so an older profile is re-described once on the
  next run. Existing resume files are still never modified.
- **Status:** 🟢 Fixed
- **Evidence:** `src/tools/resume_descriptions/models.py`,
  `src/tools/resume_descriptions/messages.py`,
  `src/tools/resume_descriptions/store.py`;
  `tests/unit/test_resume_descriptions/test_describe.py`
  (`test_parse_description_reads_highlights_and_ai_coding_tools`),
  `tests/unit/test_resume_descriptions/test_match.py`
  (`test_build_match_messages_include_the_richer_profile_fields`),
  `tests/unit/test_resume_descriptions/test_store.py`
  (`test_is_fresh_rejects_an_old_profile_version`,
  `test_ensure_descriptions_redescribes_an_old_profile_version`). Live cold-pool
  run: five profiles stored as version 2 with highlights/AI tools; the real job
  matched `fit=strong`. Commit (uncommitted).
