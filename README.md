# AutoJobApply

A [LangGraph](https://langchain-ai.github.io/langgraph/) agent that logs in to
LinkedIn, searches for jobs, selects the **Easy Apply** filter, and opens a
job's **Easy Apply** application form through a real browser (via
[browser-use](https://github.com/browser-use/browser-use)).

> Status: **Task 1 + Task 2** — log in to LinkedIn, search `"software engineer"`,
> select the Easy Apply filter, then pick a job and open its Easy Apply form. The
> graph runs end-to-end in **dry-run** mode (no browser, no network); the browser
> layer is wired but opt-in. **No application is submitted** and no form fields
> are filled.

## Behaviour

The graph is `START -> ingest -> browse -> verify -> END`:

1. **ingest** — validates the LinkedIn URL and the search query.
2. **browse** — runs both tasks in **one browser session**:
   - **Task 1:** opens Chromium, navigates to the login page, and checks whether
     you are logged in. If not, it **waits for you to log in** in the browser
     window (up to `AUTOJOB_SESSION_LOGIN_TIMEOUT_SECONDS`). Once logged in, it
     opens the jobs search tab, **types the query** (default `"software engineer"`)
     into the search bar and submits it, then selects the **Easy Apply** filter on
     the results page.
   - **Task 2:** reads the job list from those results, opens the first job that
     offers Easy Apply (skipping external-apply jobs), clicks its **Easy Apply**
     button, and confirms the application form opened. It stops there — nothing
     is submitted.
3. **verify** — passes only when you are logged in, the search returned results,
   the Easy Apply filter is selected, and a job's Easy Apply form opened.
   Otherwise the run fails and a full-page screenshot plus the page URL are
   recorded under `data/debug/`.

The browser interaction is deterministic (browser-use's CDP actor API); no LLM
is involved. The login gate is human: your session is stored in the persistent
Chromium profile under `data/profile`, so later runs skip the wait.

## Requirements

- Python 3.11 or 3.12
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync                        # core (no browser)
cp .env.example .env           # optional; defaults are safe
```

To enable real browser automation:

```bash
uv sync --extra browser
uvx playwright install chromium
```

## Run

```bash
# Offline dry run - validates the wiring, no browser is launched.
uv run autojob --dry-run

# Real run - opens Chromium, waits for login, searches, opens Easy Apply.
uv run autojob --no-dry-run
uv run autojob --no-dry-run --query "software engineer"
```

Exit code is `0` only when login succeeds, the search returns results, the Easy
Apply filter is selected, and a job's Easy Apply form opens. Add `--json` for the
raw final state.

The graph is also discoverable by the LangGraph CLI/Studio (installed in the
`dev` group):

```bash
uv run langgraph dev
```

## Layout

```
src/
  configuration.py   Typed settings from AUTOJOB_* environment variables
  state.py           The graph's shared state (Task1Outcome, Task2Outcome)
  graph.py           Graph assembly (START -> ingest -> browse -> verify -> END)
  nodes/
    ingest.py        Validate the LinkedIn URL and search query
    browse.py        Task 1 (log in, search, filter) + Task 2 (open Easy Apply)
    verify.py        Confirm both tasks' acceptance criteria
  tools/
    browser.py       browser-use session wrapper (opt-in); run_task1 / run_agent
    linkedin.py      Pure LinkedIn URL/text helpers
  main.py            CLI entry point
tests/
  unit/              Fast, offline tests
  integration/       Opt-in live browser test (set AUTOJOB_LIVE_URL)
```

## Safety rails

- The browser is **opt-in**: `--no-dry-run` is required to launch it.
- **Login gate:** a real run pauses until you log in; it never types credentials.
- Task 2 only **opens** the Easy Apply form — it never fills fields or submits an
  application.
- On failure the page URL and a screenshot are saved for debugging.
- The Chromium profile under `data/profile` persists logins and is gitignored.
