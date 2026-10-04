# AutoJobApply

A [LangGraph](https://langchain-ai.github.io/langgraph/) agent that logs in to
LinkedIn, searches for jobs, and selects the **Easy Apply** filter through a real
browser (via [browser-use](https://github.com/browser-use/browser-use)).

> Status: **Task 1** — log in to LinkedIn, search `"software engineer"`, and
> select the Easy Apply filter. The graph runs end-to-end in **dry-run** mode
> (no browser, no network); the browser layer is wired but opt-in. No application
> is submitted and no form fields are filled.

## Task 1 behaviour

The graph is `START -> ingest -> browse -> verify -> END`:

1. **ingest** — validates the LinkedIn URL and the search query.
2. **browse** — opens Chromium, navigates to the login page, and checks whether
   you are logged in. If not, it **waits for you to log in** in the browser
   window (up to `AUTOJOB_SESSION_LOGIN_TIMEOUT_SECONDS`). Once logged in, it
   opens the jobs search tab, **types the query** (default `"software engineer"`)
   into the search bar and submits it, then selects the **Easy Apply** filter on
   the results page.
3. **verify** — passes only when you are logged in, the search returned results,
   and the Easy Apply filter is selected. Otherwise the run fails and a
   full-page screenshot plus the page URL are recorded under `data/debug/`.

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

# Real run - opens Chromium, waits for login, searches, selects Easy Apply.
uv run autojob --no-dry-run
uv run autojob --no-dry-run --query "software engineer"
```

Exit code is `0` only when login succeeds, the search returns results, and the
Easy Apply filter is selected. Add `--json` for the raw final state.

The graph is also discoverable by the LangGraph CLI/Studio (installed in the
`dev` group):

```bash
uv run langgraph dev
```

## Layout

```
src/
  configuration.py   Typed settings from AUTOJOB_* environment variables
  state.py           The graph's shared state schema
  graph.py           Graph assembly (START -> ingest -> browse -> verify -> END)
  nodes/
    ingest.py        Validate the LinkedIn URL and search query
    browse.py        Log in (human gate), search jobs, select Easy Apply
    verify.py        Confirm login + results + Easy Apply filter
  tools/
    browser.py       browser-use session wrapper (opt-in)
    linkedin.py      LinkedIn URL/text helpers (login detection, search URL)
  main.py            CLI entry point
tests/
  unit/              Fast, offline tests
  integration/       Opt-in live browser test (set AUTOJOB_LIVE_URL)
```

## Safety rails

- The browser is **opt-in**: `--no-dry-run` is required to launch it.
- **Login gate:** a real run pauses until you log in; it never types credentials
  or submits an application.
- On failure the page URL and a screenshot are saved for debugging.
- The Chromium profile under `data/profile` persists logins and is gitignored.
