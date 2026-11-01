# Task 18 — Ask for the job search query at startup

**Status:** ⬜ Not started

**Goal:** Every time the agent runs, it asks the human **what job to search
for** before launching the browser, then uses that answer as the LinkedIn jobs
search query for the whole run (Task 1 search, Task 2 results scan, Task 8's
next-job loop, and self-healing browser reopens). The answer is free text — a
job title or keywords such as `data engineer`, `python developer`, or
`machine learning engineer` — not a fixed menu.

An explicit `--query` value still wins and skips the question. A
non-interactive run (tests, piped output, LangGraph Studio) and a blank answer
keep the existing default, **"software engineer"**, so scripted runs and
existing behaviour are unchanged. The agent **never** clicks **Submit
application**.

**Preconditions**
- Task 1 logs in, opens the jobs search, types the query, and loads the results.
- Task 17 already asks the date-range question at startup; this task adds the
  query question alongside it and must not break that prompt.
- `--query` exists on the CLI today but has a constant default, so the agent
  cannot tell "not supplied" from "explicitly supplied". This task makes that
  distinction.
- `--clean-profile` and `--describe-new-resumes` are maintenance modes: they do
  not run the agent, so they must not ask the query question.

**Inputs**
- The optional `--query` CLI argument (raw string).
- The startup answer typed by the human.
- Whether stdin is interactive (a real terminal) versus piped/automated.
- The query stored in the run state, which downstream Tasks 1/2/8 and
  self-healing read.

**Steps**
1. Resolve the startup query, in this order:
   - `--query` when it was explicitly supplied;
   - otherwise the interactive startup prompt;
   - otherwise (non-interactive stdin, EOF, or Ctrl+C) the default
     **"software engineer"**.
2. Prompt before launching the browser, after login settings are loaded but
   before the graph runs. Ask a single clear question, for example
   `What job do you want to search for? [software engineer]: `. Show the default
   in the prompt so pressing Enter is an obvious, safe choice.
3. Normalize the answer: strip leading/trailing whitespace, collapse internal
   whitespace runs to single spaces, and treat an empty answer as "use the
   default". Do not lower-case, reorder, or otherwise rewrite the user's words
   (LinkedIn search is case-insensitive; the human's phrasing is preserved in
   the log).
4. Ask again only for an invalid answer — for example a value that normalizes
   to empty is not invalid, it is the default. Cap re-asks at **3** attempts,
   then fall back to the default with a clear message, mirroring Task 17's
   date-range prompt. EOF and Ctrl+C return the default cleanly without a
   traceback.
5. Carry the resolved query through `new_state(...)` into `ApplyState.search_query`
   exactly as the current `--query` path does. The run summary
   (`search      : '…'`) and the graph's `ingest`/`browse` log lines must show
   the resolved query, not the raw argument.
6. Use the resolved query everywhere the run needs it:
   - Task 1 types it into the jobs search bar and the search URL `keywords`
     parameter (URL-encoded; spaces preserved as words);
   - Task 2 and Task 8 keep scanning the same results list built from it;
   - self-healing's `JobTarget.search_query` reopens the same search after a
     crash instead of reverting to the default query.
7. Prompt order at startup: ask the **job query** first, then Task 17's
   **date range**, so the human answers "what" before "how recent". Supplying
   one flag skips only its own question; the other still prompts.
8. Keep the question out of maintenance modes (`--clean-profile`,
   `--describe-new-resumes`) and out of any path that does not launch the
   agent.
9. Do not change how Task 3 picks resumes or how Task 16 skips unmatched jobs;
   the query only selects which jobs appear in the results list.
10. Never click **Submit application**; submission remains a manual human step.

**Acceptance criteria**
- Running the agent interactively always asks for the job to search for before
  the browser launches, and the answer drives the actual LinkedIn search.
- Pressing Enter on an empty answer searches the default **"software engineer"**.
- An explicit `--query "data engineer"` skips the question and searches that
  value; it is not overwritten by the default or by a prompt.
- A non-interactive run asks nothing, logs no prompt, and defaults to
  **"software engineer"** when `--query` is omitted.
- EOF/Ctrl+C at the prompt falls back to the default without a traceback, and
  the agent continues.
- The answer is trimmed and whitespace-collapsed; the search URL `keywords`
  parameter is correctly encoded for multi-word and special-character queries
  (for example `C++ developer` and `data & analytics`).
- The prompt order is job query → date range; `--query` and `--date-range` skip
  their own questions independently.
- `--clean-profile` and `--describe-new-resumes` never prompt.
- The resolved query appears in the CLI summary and state, and self-healing
  reopens the same query after a crash.
- Unit tests cover: explicit flag wins; interactive answer used; blank defaults;
  whitespace normalization; invalid/empty re-ask cap; EOF/Ctrl+C default;
  non-interactive default; maintenance modes skip the prompt; both prompts in
  order; URL encoding. Live-browser test proves a non-default query (for
  example `data engineer`) is typed into the real LinkedIn search and the
  results load without submitting an application.
- Never click **Submit application**; submission remains a manual human step.

**Notes**
- **New module, one concern.** Add `src/search_query_choice.py` with
  `choose_search_query(...)` (pure resolution + prompt, injectable
  `input_func`/`stream`/`interactive` like `src/date_range_choice.py`) and keep
  `src/main.py` as the thin caller. Stay well under the 415-line limit.
- **Do not duplicate the prompt logic.** Follow Task 17's
  `choose_date_range` structure (explicit value → interactive prompt →
  non-interactive default) so both startup questions behave the same way.
- **CLI default.** Change `--query` to `default=None` (or an explicit
  "unset" sentinel) and resolve before `new_state(...)`; keep
  `DEFAULT_SEARCH_QUERY = "software engineer"` as the single source of the
  default. Update `--help` to say the question is asked when omitted.
- **Interrelated updates:** `src/main.py`, `src/state.py`
  (`search_query`/`new_state` defaults and docs), `src/nodes/ingest.py`,
  `src/nodes/browse.py`, `src/tools/browser.py`,
  `src/tools/linkedin_search/orchestrator.py`,
  `src/tools/linkedin_search/search_box.py`,
  `src/tools/self_healing/models.py`,
  `src/tools/self_healing/recovery/`, `README.md`, and their tests. Existing
  callers that omit the query must keep working with the default.
- **No query mutation.** Keep the human's query in logs/state; do not rewrite it
  into a different role (for example do not map "SWE" to "software engineer").
- **Task text sync (done at creation, per `AGENTS.md`):** Task 1, Task 2,
  Task 6, Task 9, and the `task/task.md` index were updated to describe the
  **resolved/chosen query** (default `software engineer`) instead of a
  hard-coded "software engineer" search, so no older spec contradicts this task.
- **Tests:** add `tests/unit/test_search_query_choice.py` plus updates where the
  CLI/state is constructed, and a focused live-browser check that a non-default
  query reaches the real search results.
- **Live verification required:** run the agent against the real site, type a
  non-default query at the prompt, and confirm in the browser that the search
  box and results URL contain it, the date-range question still follows, and
  the results list loads. Do not mark the task done from unit tests alone.
- **Bug log:** if implementation exposes a new bug, add
  `known Bugs/task_18_bugs.md` and its row in `known Bugs/bug_log.md` with the
  symptom, root cause, fix, status, and evidence, as required by `AGENTS.md`.
- Never click **Submit application**; submission remains a manual human step.
