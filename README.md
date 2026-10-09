# AutoJobApply

A [LangGraph](https://langchain-ai.github.io/langgraph/) agent that logs in to
LinkedIn, searches for jobs, selects the **Easy Apply** filter, opens a job's
**Easy Apply** application form, picks the best-matching resume, and starts
filling the form — all through a real browser (via
[browser-use](https://github.com/browser-use/browser-use)).

> Status: **Tasks 1-5** — log in, search `"software engineer"`, select the Easy
> Apply filter, open a job's Easy Apply form, read the job description, select the
> best-matching resume, fill known fields + attach the resume, and ask you in the
> browser about any question it cannot answer, remembering your answer for next
> time. The graph runs end-to-end in **dry-run** mode (no browser, no network);
> the browser layer is wired but opt-in. **No application is ever submitted.**

## Behaviour

The graph is `START -> ingest -> browse -> match -> fill -> cleanup -> verify -> END`:

![Graph diagram](docs/graph.png)

> Regenerate the diagram (or the Mermaid source) with
> `python -m src.visualize --out docs/graph.png --mermaid-out docs/graph.mmd`.

1. **ingest** — validates the LinkedIn URL and the search query.
2. **browse** — runs Tasks 1-3's browser work in **one session**:
   - **Task 1:** opens Chromium, navigates to the login page, and checks whether
     you are logged in. If not, it **waits for you to log in** in the browser
     window (up to `AUTOJOB_SESSION_LOGIN_TIMEOUT_SECONDS`). Once logged in, it
     runs LinkedIn's **AI job search** — clicking the **"Try AI job search"**
     control and typing the query (default `"software engineer"`) into the AI
     prompt ("Describe the job you want") — then selects the **Easy Apply** filter
     on the results page. The classic jobs search bar is not used.
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
4. **fill** — **Task 4:** enumerates the still-open Easy Apply form, fills the
   known answers, attaches the chosen resume — preferring a resume already listed
   on the form over uploading a duplicate — and advances multi-step forms. It
   **stops before Submit application** and never clicks it.
   - **Steps 2-3 (LLM agent):** when `AUTOJOB_LLM_MODEL` and an
     `OPENROUTER_API_KEY` are set, browser-use's LLM agent is the **sole**
     mechanism for deciding which enumerated fields already have a known answer
     (from `data/answers.json`) and filling them. It runs behind a
     navigation/submit click guard and a restricted toolset. There is no
     deterministic store fallback: fields the agent leaves empty go straight to
     Task 5. With no model configured, the offline deterministic fill is used
     instead (no LLM at all).
   - **Task 5 (inside fill):** when a question is unknown (including anything the
     agent left empty), the agent shows a banner in the browser window saying it
     does not know the answer, **pauses for you to type it into the form field on
     the page** (the banner has no input of its own), reads the value you enter,
     fills the field, and saves the normalized question → answer mapping. The same
     question is answered automatically next run. Choice fields (selects/radios)
     list their allowed options in the banner, and an answer that matches a visible
     option label is mapped to the right value. Controls the form has **already
     filled** (e.g. LinkedIn's pre-filled *Email address* / *Phone country code*
     selects) are left as-is and never asked about. Click **Skip** in the banner to
     skip on purpose. Set `AUTOJOB_SESSION_ASK_HUMAN=false` to leave unknown
     questions unanswered instead of prompting. Questions you skip or leave
     unanswered are recorded and can be answered on a later run.
5. **cleanup** — closes the shared browser session on every path.
6. **verify** — passes only when all of the above succeeded. Otherwise the run
   fails and a full-page screenshot plus the page URL are recorded under
   `data/debug/`.

The browser interaction is deterministic (browser-use's CDP actor API) except for
Task 4 steps 2-3, which are driven by a browser-use LLM agent (OpenRouter) when a
model is configured; the resume matching is deterministic keyword/weight scoring.
With no model configured, **no LLM is involved** at all. The login gate is human:
your session is stored in the persistent Chromium profile under `data/profile`, so
later runs skip the wait.

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
`data/answers.json` (keys are normalized automatically). Task 5 also writes to
this file when it asks you a new question in the browser, so answers persist
across runs. For example:

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
    browser.py       browser-use session wrapper (opt-in); shared browser primitives,
                     run_agent / run_full_agent, and Task 5's ask-the-human banner
    linkedin.py      Pure LinkedIn URL/text helpers
    linkedin_search.py             Task 1: log in, search jobs, select Easy Apply filter
    linkedin_job_selection.py      Task 2: select a job, open its Easy Apply form
    linkedin_best_matching_resume.py
                     Task 3: read the job description, pick the best-matching resume
    linkedin_easy_apply_fill.py    Task 4: fill the Easy Apply form, attach the resume
    agent_fill.py                  Task 4 steps 2-3: browser-use LLM agent fill (optional)
    matching.py      Pure resume-to-job scoring (explainable, deterministic)
    answers.py       Question -> answer store (read by Task 4, written by Task 5)
    forms.py         Pure Easy Apply form helpers (resume match, next/submit)
  main.py            CLI entry point
resumes/             Candidate resumes (.pdf, .docx, .txt, .md)
tests/
  unit/              Fast, offline tests
  integration/       Opt-in live browser / real-resume tests
```

## Troubleshooting

- **"another browser is already using the AutoJobApply profile …"** — another
  AutoJobApply run (or a window left open by an earlier one) still owns
  `data/profile`, so this launch stops instead of force-closing it. Closing a
  live browser that another run is driving tears down its CDP WebSocket and the
  reconnect attempts fail (`ConnectionRefusedError` / `WinError 1225`). Finish or
  close that run and retry; to force-close it deliberately:

  ```bash
  uv run autojob --clean-profile
  ```

  This only closes browser processes whose command line references the dedicated
  `data/profile`, so your normal Chrome is untouched. Set
  `AUTOJOB_SESSION_CLEAN_STALE_PROFILE=false` to skip the lock recovery.

- **"Browser process … exited before CDP became available"** — a **crashed**
  previous run left Chromium's single-instance lock in `data/profile` (with no
  live process). The agent clears that stale lock automatically on the next
  launch. If a browser is still alive, it stops with the message above instead of
  killing it; use `uv run autojob --clean-profile` to force it.

- **`Exception ignored in: … I/O operation on closed pipe` after a run** — a
  harmless Windows `asyncio` shutdown artifact from the browser subprocess. The
  CLI filters exactly that message, so it no longer clutters the output.

## Safety rails

- The browser is **opt-in**: `--no-dry-run` is required to launch it.
- **Login gate:** a real run pauses until you log in; it never types credentials.
- Task 4 fills **known** answers only, attaches the chosen resume, and **never
  clicks Submit application** — submission stays a manual human step. When the
  optional LLM agent drives steps 2-3, a click/submit guard disables every
  navigation, close, and Submit control for the duration of the agent run, and its
  toolset excludes navigation, tab, file, and resume-upload actions.
- Task 5 never guesses: an unknown question pauses on a browser banner and waits
  for you to type the answer into the form field. Answers are stored in
  `data/answers.json` (no credentials) and reused.
- Unknown questions that you skip or leave unanswered are recorded rather than
  guessed.
- Task 3 only **reads** resumes — it never renames, moves, or edits them.
- On failure the page URL and a screenshot are saved for debugging.
- The Chromium profile under `data/profile` persists logins and is gitignored.
