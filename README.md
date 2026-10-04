# AutoJobApply

A [LangGraph](https://langchain-ai.github.io/langgraph/) agent that logs in to
LinkedIn, searches for jobs, selects the **Easy Apply** filter, opens a job's
**Easy Apply** application form, picks the best-matching resume, and starts
filling the form — all through a real browser (via
[browser-use](https://github.com/browser-use/browser-use)).

> Status: **Tasks 1-4** — log in, search `"software engineer"`, select the Easy
> Apply filter, open a job's Easy Apply form, read the job description, select the
> best-matching resume, and fill known fields + attach the resume. The graph runs
> end-to-end in **dry-run** mode (no browser, no network); the browser layer is
> wired but opt-in. **No application is ever submitted.**

## Behaviour

The graph is `START -> ingest -> browse -> match -> fill -> cleanup -> verify -> END`:

1. **ingest** — validates the LinkedIn URL and the search query.
2. **browse** — runs Tasks 1-3's browser work in **one session**:
   - **Task 1:** opens Chromium, navigates to the login page, and checks whether
     you are logged in. If not, it **waits for you to log in** in the browser
     window (up to `AUTOJOB_SESSION_LOGIN_TIMEOUT_SECONDS`). Once logged in, it
     opens the jobs search tab, **types the query** (default `"software engineer"`)
     into the search bar and submits it, then selects the **Easy Apply** filter on
     the results page.
   - **Task 2:** reads the job list from those results, opens the first job that
     offers Easy Apply (skipping external-apply jobs), clicks its **Easy Apply**
     button, and confirms the application form opened.
   - **Task 3 (read):** reads the open job's title, company, location, and
     description body from the details pane.
   The session is left **open** (registered under an opaque `browser_run_id`) so
   Task 4 can fill the same Easy Apply modal.
3. **match** — Task 3's offline half: lists every resume in the folder
   (`.pdf`, `.docx`, `.txt`, `.md`), extracts its text, scores it against the job
   description, and selects the highest scorer with a written rationale. Ties go
   to the most recently modified file. Resume files are never modified.
4. **fill** — **Task 4:** enumerates the still-open Easy Apply form, answers every
   question it already knows from the answer store (`data/answers.json`), attaches
   the chosen resume — preferring a resume already listed on the form over
   uploading a duplicate — and advances multi-step forms. It **stops before
   Submit application** and never clicks it. Unknown questions are recorded and
   left for Task 5.
5. **cleanup** — closes the shared browser session on every path.
6. **verify** — passes only when all of the above succeeded. Otherwise the run
   fails and a full-page screenshot plus the page URL are recorded under
   `data/debug/`.

The browser interaction is deterministic (browser-use's CDP actor API) and the
resume matching is deterministic keyword/weight scoring; **no LLM is involved**.
The login gate is human: your session is stored in the persistent Chromium
profile under `data/profile`, so later runs skip the wait.

## Requirements

- Python 3.11 or 3.12
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync                        # core (no browser); includes pypdf for resumes
cp .env.example .env           # optional; defaults are safe
```

Put one or more resumes in `resumes/` (supported: `.pdf`, `.docx`, `.txt`, `.md`).

To answer form questions automatically, add them to the answer store
`data/answers.json` (keys are normalized automatically), for example:

```json
{
  "phone number": "+61 400 000 000",
  "are you authorised to work in australia": "Yes",
  "years of experience": "5"
}
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

# Real run - opens Chromium, waits for login, searches, opens Easy Apply,
# reads the job, picks a resume, and fills the form (never submits).
uv run autojob --no-dry-run
uv run autojob --no-dry-run --query "software engineer" --resumes-dir ./resumes
```

Exit code is `0` only when all acceptance criteria pass. Add `--json` for the raw
final state.

The graph is also discoverable by the LangGraph CLI/Studio (installed in the
`dev` group):

```bash
uv run langgraph dev
```

## Layout

```
src/
  configuration.py   Typed settings from AUTOJOB_* environment variables
  state.py           The graph's shared state (Task1-4 outcomes, JobDescription)
  graph.py           Graph assembly (START -> ingest -> browse -> match -> fill -> cleanup -> verify -> END)
  nodes/
    ingest.py        Validate the LinkedIn URL and search query
    browse.py        Tasks 1-3 browser work (login, search, Easy Apply, description)
    match.py         Task 3: select the best-matching resume (offline)
    fill.py          Task 4: fill the Easy Apply form + attach the resume
    cleanup.py       Close the shared browser session
    verify.py        Confirm every task's acceptance criteria
  tools/
    browser.py       browser-use session wrapper (opt-in); run_agent / run_full_agent
    linkedin.py      Pure LinkedIn URL/text helpers
    matching.py      Pure resume-to-job scoring (explainable, deterministic)
    resumes.py       Resume discovery, text extraction, and selection
    answers.py       Question -> answer store (read by Task 4, written by Task 5)
    forms.py         Pure Easy Apply form helpers (resume match, next/submit)
  main.py            CLI entry point
resumes/             Candidate resumes (.pdf, .docx, .txt, .md)
tests/
  unit/              Fast, offline tests
  integration/       Opt-in live browser / real-resume tests
```

## Safety rails

- The browser is **opt-in**: `--no-dry-run` is required to launch it.
- **Login gate:** a real run pauses until you log in; it never types credentials.
- Task 4 fills **known** answers only, attaches the chosen resume, and **never
  clicks Submit application** — submission stays a manual human step.
- Unknown questions are left for Task 5 rather than guessed.
- Task 3 only **reads** resumes — it never renames, moves, or edits them.
- On failure the page URL and a screenshot are saved for debugging.
- The Chromium profile under `data/profile` persists logins and is gitignored.
