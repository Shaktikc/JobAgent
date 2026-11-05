# JobAgent

**An AI-powered LinkedIn Easy Apply assistant.** It searches for jobs, picks the
resume that fits best, and fills out the application in a real browser — and it
can submit automatically when you ask it to.

**The problem:** I was spending more than an hour every day just applying for
jobs on LinkedIn — opening postings, re-reading descriptions, choosing a resume,
and filling the same Easy Apply forms over and over. So I built this agentic AI
system to take over the repetitive work: searching, resume matching, form
filling, and — when you enable it — submission too. Manual review remains the
default; automatic submission is opt-in per run.

Built with [LangGraph](https://langchain-ai.github.io/langgraph/),
[browser-use](https://github.com/browser-use/browser-use) (CDP), and any
OpenAI-compatible LLM endpoint.

> **Status:** personal project, actively developed. LinkedIn changes its UI
> often, so the agent discovers each Easy Apply form at runtime instead of
> relying on fixed steps or selectors.

## Why it's interesting

Most "AI apply" tools hand the whole task to an LLM and hope for the best.
JobAgent splits the work:

- **Deterministic browser automation** handles the clicking, typing, pagination,
  and form navigation.
- **The LLM only makes judgement calls** — which resume fits, and which stored
  answer answers a question.
- **Every answer is grounded.** The model must copy a stored value or derive one
  from stored facts, and cite the keys it used. It never invents an answer.
- **When it doesn't know something, it asks you** — directly in the browser —
  and remembers your answer for next time.

## Highlights

- 🔎 Searches LinkedIn (using its AI job search when available) and applies the
  **Easy Apply** + **date posted** filters.
- 📄 Profiles every resume with an LLM and applies only when the match is
  **strong** (strict mode is the default).
- 🧠 Fills dynamic, multi-step Easy Apply forms: text, selects, radios,
  checkboxes, resume attachment, and validation errors.
- 💬 Answers unknown required questions through an in-page banner, then stores
  the answer for future runs.
- 🚀 **Manual or automatic submission** — review and submit yourself, or let the
  agent submit a fully validated application once and verify LinkedIn's
  confirmation.
- ✍️ Answers job-specific free-text questions ("Why do you want to work here?")
  from the current job description and your resume, with cited evidence.
- 🖥️ Shows a **live status panel** on the LinkedIn page describing each step and
  every LLM decision.
- 🛠️ **Self-heals** structural form failures: captures evidence, logs a bug,
  optionally invokes an OpenCode repair agent, then reopens the same job.
- 🔁 Repeats for the next unapplied job, skipping jobs already marked
  **Applied** and paginating when a page is exhausted.
- 🧪 Runs end-to-end in **dry-run** mode with no browser and no network.

## How it works

```
START → ingest → browse → match → fill → await_submit → next_job → … → cleanup → verify → END
```

![Graph diagram](docs/graph.png)

> Regenerate it with
> `python -m src.visualize --out docs/graph.png --mermaid-out docs/graph.mmd`.

1. **Validate** — checks the LinkedIn URL, search query, date range, and
   submission mode.
2. **Browse** — opens Chromium and waits for you to log in (it never types
   credentials). It then searches for jobs, applies the Easy Apply filter, and
   selects **Past 24 hours** or **Past week**. Already-applied cards are skipped,
   whole pages of applied jobs are paginated through, and when one date range is
   exhausted the agent falls back to the other.
3. **Match** — builds an LLM profile for each resume in `resumes/`, rates every
   candidate against the job, and picks the best one. In strict mode the job is
   only opened when the match is `strong`; otherwise it is skipped cleanly
   without ever opening the form.
4. **Fill** — walks the Easy Apply form step by step. Required (`*`) questions
   are answered from `data/answers.json`; the LLM may copy a stored answer or
   derive one the store entails. Job-specific questions use the job description
   and selected resume. Anything unresolved is handed to you in the browser.
   The agent attaches the resume and advances multi-step forms.
5. **Submit** — before the browser launches (after the date-range question), you
   choose **manual** (default) or **automatic** submission for the whole run;
   `--submission-mode manual|auto` skips the question. In manual mode the browser
   stays open on the terminal step for you to review and submit. In automatic
   mode, the agent re-checks required answers and native validation, requires one
   enabled **Submit application** control on the terminal step, clicks it once,
   and waits up to
   `AUTOJOB_SESSION_AUTO_SUBMIT_TIMEOUT_SECONDS` (default `30`) for a **new**
   confirmation — "Your application was sent…", "Application sent", "Done", or
   the job's card flipping to **Applied**. A missing confirmation or ambiguous
   control stops with `needs_review` and leaves the browser open for manual
   review; the click is never retried, including through self-healing. Diagnostic
   evidence is saved under `data/debug/task22/`. The chosen mode survives the
   next-job loop and self-healing recovery.
6. **Repeat** — returns to the results, opens the next unapplied Easy Apply job,
   and runs the loop again. Stops after `AUTOJOB_SESSION_MAX_JOBS` submissions
   (default `35`; `0` = until no unapplied jobs remain).
7. **Cleanup & verify** — releases the session but leaves the Chromium window
   open so you can inspect it, then validates the run.

## Safety and guardrails

- **The browser is opt-in.** Nothing launches without `--no-dry-run`.
- **Human login gate.** A real run pauses until you log in; credentials are never
  read, typed, or stored.
- **Manual submission is the default.** Automatic submission must be chosen
  explicitly at startup or with `--submission-mode auto`, and it only clicks
  **Submit application** once a fully completed, validated form reaches its real
  terminal step. It then requires a fresh site confirmation before recording the
  application; an uncertain result stops for manual review instead of retrying.
- **No invented answers.** LLM answers must cite stored keys or evidence from the
  job description/resume; unsupported answers are rejected and sent to you.
- **Resumes are read-only.** The agent never renames, edits, or overwrites them.
  The one exception is the intake folder, where a fully described resume is moved
  into the pool without changing its bytes.
- **Nothing is submitted during recovery.** Self-healing stops at the review step.
- **Failure evidence is saved** (screenshot + URL) under `data/debug/`.

> ⚠️ **Use responsibly.** Automating LinkedIn may violate its User Agreement and
> could affect your account. This project is shared for personal/educational use.
> Review every application and use it at your own risk.

## Requirements

- Python 3.11 or 3.12
- [uv](https://docs.astral.sh/uv/)
- Optional: [OpenCode](https://opencode.ai/) CLI, only if you enable the
  self-healing repair hook

## Quick start

```bash
# 1. Install the core dependencies (no browser yet)
uv sync

# 2. Create your local environment file (optional; defaults are safe)
cp .env.example .env

# 3. Add one or more resumes (.pdf, .docx, .txt, .md)
#    to the resumes/ folder

# 4. Validate the whole graph offline
uv run jobagent --dry-run

# 5. For a real run, install the browser layer once
uv sync --extra browser
uvx playwright install chromium

# 6. Launch the agent
uv run jobagent --no-dry-run
```

On the first real run, log in to LinkedIn in the Chromium window that opens. The
persistent profile in `data/profile` keeps you logged in for later runs.

To add a resume later, drop it in `resumes/new/`. The next matching run describes
it and moves it into `resumes/`, or you can do that immediately:

```bash
uv run jobagent --describe-new-resumes
```

## Configuration

Copy `.env.example` to `.env` and set at least an API key and a model. Any
OpenAI-compatible endpoint works via `AUTOJOB_LLM_BASE_URL`.

```env
OPENROUTER_API_KEY=sk-or-...
AUTOJOB_LLM_MODEL=xiaomi/mimo-v2.6-pro       # general-purpose
AUTOJOB_RESUME_LLM_MODEL=                    # optional: resume matching
AUTOJOB_ANSWERS_LLM_MODEL=                   # optional: answer selection
```

Task-specific model overrides are independent: a resume override never changes
answer selection, the general model, or the self-healing agent. The startup log
prints the model used for each purpose.

### Useful variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTOJOB_RESUMES_DIR` | `./resumes` | Resume pool |
| `AUTOJOB_NEW_RESUMES_DIR` | `./resumes/new` | Intake folder for new resumes |
| `AUTOJOB_DATA_DIR` | `./data` | Browser profile, answer stores, debug output |
| `AUTOJOB_SESSION_REQUIRE_RESUME_MATCH` | `true` | Apply only on a strong resume match |
| `AUTOJOB_SESSION_MAX_JOBS` | `35` | Max submissions per run (`0` = unlimited) |
| `AUTOJOB_SESSION_ASK_HUMAN` | `true` | Prompt in-browser for unknown answers |
| `AUTOJOB_SESSION_HEADLESS` | `false` | Run Chromium without a visible window |
| `AUTOJOB_SESSION_KEEP_OPEN_TIMEOUT_SECONDS` | `1800` | How long to leave the browser open at the end |
| `AUTOJOB_SESSION_AUTO_SUBMIT_TIMEOUT_SECONDS` | `30` | Wait for automatic-submission confirmation |
| `AUTOJOB_SELF_HEAL_ENABLED` | `true` | Recover structural Easy Apply failures |
| `AUTOJOB_SELF_HEAL_REPAIR_COMMAND` | unset | Optional OpenCode repair hook |

The full list, with comments, lives in [`.env.example`](.env.example).

### The answer store

Auto-answered questions come from `data/answers.json`. Keys are questions and
values are answers, written by you or by the in-browser prompt:

```json
{
  "phone number": "+61 400 000 000",
  "are you authorised to work in australia": "Yes",
  "years of experience": "5"
}
```

The LLM matches questions by meaning, may derive an answer the stored facts
entail, and always records the source keys it used. Derived answers are cached
separately in `data/derived_answers.json`, so `answers.json` stays
human-confirmed. Job-specific free-text answers are generated per job and never
written to either file.

## CLI

```bash
# Offline wiring check (default)
uv run jobagent --dry-run

# Real run: asks for date range and submission mode
uv run jobagent --no-dry-run
uv run jobagent --no-dry-run --date-range week
uv run jobagent --no-dry-run --query "software engineer" --resumes-dir ./resumes

# Skip the submission prompt
uv run jobagent --no-dry-run --submission-mode auto
uv run jobagent --no-dry-run --submission-mode manual

# Resume intake, profile cleanup, raw JSON output
uv run jobagent --describe-new-resumes
uv run jobagent --clean-profile
uv run jobagent --json
```

`--date-range` accepts `24h`/`past_24_hours` or `week`/`past_week`. When omitted,
an interactive terminal asks which range to scan first (default: **Past 24
hours**). Non-interactive runs use that default. When the chosen range is
exhausted, the agent falls back to the other one.

Exit code is `0` only when all acceptance criteria pass.

The graph is also discoverable by LangGraph Studio:

```bash
uv run langgraph dev
```

## Self-healing

When a fill stops for a structural reason (no resume control, a step that won't
advance, a missing button, an exception), the agent:

1. captures a screenshot, DOM excerpt, visible text, console lines, form state,
   and the exception under `data/debug/self_healing/`;
2. writes a deduplicated `BUG-NNN` entry to the bug log;
3. closes the failed browser and reopens the exact job URL in a fresh session;
4. clicks **Easy Apply** and re-fills the same job — never submitting;
5. stops after `AUTOJOB_SELF_HEAL_MAX_ATTEMPTS` (default `3`) and preserves the
   evidence.

An optional repair hook can hand the bundle to the OpenCode agent, run its
tests, and reload the browser/fill modules before retrying:

```env
AUTOJOB_SELF_HEAL_REPAIR_COMMAND=uv run python scripts/self_heal_repair.py
AUTOJOB_SELF_HEAL_TEST_COMMAND=uv run pytest -q
```

The repair agent uses `AUTOJOB_SELF_HEAL_REPAIR_MODEL` (default
`deepseek/deepseek-v4.1-flash-1017`) and never falls back to the general model.

## Project layout

```
src/
  configuration.py    Typed settings from AUTOJOB_* variables
  graph.py            LangGraph assembly
  nodes/              Graph nodes: ingest, browse, match, fill, submit loop, cleanup, verify
  state/              Shared state models
  date_range*.py      Past 24 hours / Past week selection
  main.py             CLI entry point
  tools/
    browser/          browser-use wrapper, sessions, CDP primitives
    linkedin*.py      LinkedIn search, filters, job selection, pagination, apply loop
    linkedin_easy_apply_fill/
                      Dynamic Easy Apply form discovery and filling
    linkedin_best_matching_resume/
                      Job description reading + resume matching
    resume_descriptions/
                      LLM resume profiles, match prompts, versioned store
    llm_answers.py    Grounded answer selection from the store
    llm_answer_reasoning.py
                      Match-or-derive logic with source citations
    job_context*.py   Per-job context for free-text answers
    linkedin_ask_human/
                      In-browser question banner and answer capture
    self_healing/     Failure evidence, bounded recovery, optional repair hook
scripts/              Self-healing repair wrapper
resumes/              Resume pool (.pdf, .docx, .txt, .md)
resumes/new/          Intake folder for new resumes
tests/                Unit tests + opt-in live browser tests
```

## Testing

```bash
uv run pytest -q        # fast, offline tests
uv run ruff check .     # lint
```

Live browser tests under `tests/integration/` are opt-in and use a real Chromium
session.

## Troubleshooting

- **"another browser is already using the JobAgent profile"** — a previous
  run still owns `data/profile`. Close that window or run
  `uv run jobagent --clean-profile`. Only browsers using the dedicated profile are
  closed; your normal Chrome is untouched.
- **"Browser process … exited before CDP became available"** — a crashed run
  left a stale single-instance lock. The next launch clears it automatically. If a
  live browser still holds the profile, close it or use `--clean-profile`.
- **"I/O operation on closed pipe" after a run** — a harmless Windows asyncio
  shutdown message from the browser subprocess; the CLI filters it.

## Further reading

- [Submission modes and verification](docs/task22-submission.md)
- [Required-answer recovery](docs/task24-required-answer-recovery.md)
- [Answer type conversion](docs/task25-answer-type-conversion.md)
- [Validation recovery](docs/task20-validation-recovery.md)
- [Answer completion feedback](docs/task26-answer-completion.md)
- [Resume matching verification](docs/task16-verification.md)

The `autojob` command remains available as an alias. Existing `AUTOJOB_*`
settings remain supported.
