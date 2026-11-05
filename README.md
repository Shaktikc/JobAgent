# AutoJobApply

A [LangGraph](https://langchain-ai.github.io/langgraph/) agent that logs in to
LinkedIn, searches for jobs, selects the **Easy Apply** filter, picks the
best-matching resume, opens the job's **Easy Apply** form only when the resume
matches, and starts filling it — all through a real browser (via
[browser-use](https://github.com/browser-use/browser-use)).

> Status: **Tasks 1-13 and 15-17** — log in, search `"software engineer"`, choose
> **Date posted → Past 24 hours** or **Past week** at startup, select the Easy
> Apply filter, read the job description, select the best-matching resume, open
> Easy Apply only on a match, fill known fields + attach the resume, and ask you in the
> browser about any question it cannot answer, remembering your answer for next
> time. When the chosen date range is exhausted, the agent falls back to the other
> range (Past 24 hours ⇄ Past week). For each form question an **LLM (Task 4.1/10)** classifies the question and
> answers it from the store — copying a stored answer, or **deriving** one the
> stored entries entail (e.g. a stored "years of experience with AI: 5" answers
> "Experience on AI? [Yes/No]" as **Yes**), always citing the stored key(s) it used
> and never inventing an answer. Choose **manual** (default) or **automatic**
> submission at startup (Task 22). After a confirmed submission, the agent
> returns to the results list, selects the next unapplied job, and repeats. A live
> **status panel (Task 9)** on the LinkedIn page shows each step in plain language
> and exactly what the **LLM** is doing. The graph
> runs end-to-end in **dry-run** mode (no browser, no network); the browser layer
> is wired but opt-in. Automatic submission requires an explicit startup choice
> or `--submission-mode auto`; otherwise you review and submit each application.

## Behaviour

The graph is `START -> ingest -> browse -> match -> fill -> await_submit -> next_job -> match -> ... -> cleanup -> verify -> END` (the `await_submit`/`next_job` pair is Task 8's loop):

![Graph diagram](docs/graph.png)

> Regenerate the diagram (or the Mermaid source) with
> `python -m src.visualize --out docs/graph.png --mermaid-out docs/graph.mmd`.

1. **ingest** — validates the LinkedIn URL, the search query, and the startup
   date range (**Past 24 hours** or **Past week**).
2. **browse** — runs Tasks 1-3's browser work in **one session**:
   - **Task 1:** opens Chromium, navigates to the login page, and checks whether
     you are logged in. If not, it **waits for you to log in** in the browser
     window (up to `AUTOJOB_SESSION_LOGIN_TIMEOUT_SECONDS`). Once logged in, it
     runs LinkedIn's **AI job search** — clicking the **"Try AI job search"**
     control and typing the query (default `"software engineer"`) into the AI
     prompt ("Describe the job you want") — then selects the **Easy Apply** filter
     and the **Date posted** range chosen at startup (**Past 24 hours** or **Past
     week**) on the results page. Applying the date filter reloads the results,
     so the agent re-checks/re-applies Easy Apply before Task 2 opens a job —
     through the URL (`f_AL=true`) so the date range is preserved. The applied
     range is verified from `f_TPR=r86400` (Past 24 hours) or `f_TPR=r604800`
     (Past week) in the results URL (a checked popover option alone is not
     enough); if the layout hides the dropdown, the agent adds that parameter to
     the current results URL while preserving the other filters. The classic jobs
     search bar is not used.
   - **Task 2:** reads the job list from those results, selects the first job that
     offers Easy Apply (skipping external-apply jobs), and reads its description.
     The **Easy Apply** button is deliberately **not** clicked yet: Task 16 matches
     a resume first and only then opens the form. Before judging the button it
     checks the details pane really shows the job it clicked (an already-applied
     job's pane has no Easy Apply button at all), and re-clicks the card once if
     the pane did not switch — so a swallowed click can no longer look like "no
     Easy Apply".
   - **Task 6:** skips cards already marked **"Applied"** (e.g. "Applied · 5
     months ago") and opens the first unapplied job instead.
   - **Task 7:** when *every* card on the current results page is **"Applied"**,
     advances the results list to the next page (up to `_MAX_RESULT_PAGES`) and
     scans it again, until an unapplied job is found or there are no more pages.
     The number of pages visited is recorded (`pages_visited`). Paginating never
     opens or applies to a job by itself.
   - **Task 17:** when every page of the startup range is exhausted and no
     unapplied Easy Apply job remains, it selects **Date posted → the other
     range** (Past 24 hours → Past week, or Past week → Past 24 hours), resets to
     page 1, keeps **Easy Apply** active, and scans it. The week list includes the
     24-hour jobs, so their applied/skipped keys carry over and are never
     reopened. Past month is out of scope.
   - **Task 3 (read):** reads the open job's title, company, location, and
     description body from the details pane.
   The session is left **open** (registered under an opaque `browser_run_id`) so
   Task 4 can fill the same Easy Apply modal.
3. **match** — Task 3's offline half: lists every resume in the folder
   (`.pdf`, `.docx`, `.txt`, `.md`), has the **LLM** (Task 3.2) write a short
   profile for each one (skills, titles, seniority, years, domain, plus factual
   highlights and any named AI coding tools) into
   `data/resume_descriptions.json`, then asks the LLM to rate every candidate and
   pick the single best-matching resume, or **none**. The LLM is the only matching
   path — there is no deterministic scoring fallback. The gate uses the LLM's
   per-candidate ratings, so a strong candidate is still selected when the model's
   first pick is only `partial`. Years-of-experience requirements are ignored
   when matching, so a candidate with fewer years than requested can still be
   rated `strong` (Task 19). Stored profiles are versioned: after a profile
   prompt/schema change, the next run re-describes the pool once instead of reusing
   weak old profiles. Resume files are never modified.
   - **Task 15:** first processes resumes placed in `resumes/new/`: Task 3.2
     describes each one, then the file is moved into `resumes/` without
     overwriting an existing resume. The description entry follows the file, and
     the moved resume joins the matching pool.
   - **Task 16 (strict resume matching, default):** the LLM also rates the fit of
     its choice (`strong` / `partial` / `none`). The agent applies **only** to a
     `strong` match against an existing resume. Anything else — `none`, `partial`,
     a missing rating, or an empty pool — is a **clean skip**: because the Easy
     Apply form was never opened, there is no form to close; the job is recorded
     with the LLM's rationale, its title is excluded from later passes, and the
     next unapplied job is selected. No upload prompt, remembered-resume fallback,
     Easy Apply click, fill, or submit happens for a skipped job. Set
     `AUTOJOB_SESSION_REQUIRE_RESUME_MATCH=false` to restore the Task 3.1
     fallbacks below.
   - **Task 2b (`open_form`):** only after `match` selects a resume does the graph
     click **Easy Apply** on the already-selected job and wait for the form. A
     skipped job goes straight to `next_job` and never reaches this node.
   - **Task 3.1 (only when strict matching is off):** when the LLM answers
     **none**, the agent first reuses a resume
     it remembered for a similar job; otherwise it shows a banner with a file
     picker, **pauses for you to upload a resume**, stores it in the folder, has
     the LLM describe it, and remembers its job profile
     (`data/resume_library.json`) so similar jobs reuse it without asking again.
     If you skip and nothing is available, the run stops instead of applying with
     an unmatching resume.
4. **fill** — **Task 4:** enumerates the still-open Easy Apply form and answers
   each question with a visible `*` on its **own label or group heading**.
   **Task 21:** every unstarred question is skipped, for any topic or control type,
   even when HTML `required`, `aria-required` or an error-message ID is present.
   Skipping happens before answer lookup, LLM selection or human prompts; existing
   values/selections stay unchanged and blank optional fields do not count as
   unknown.
   **Task 4.1** classifies every remaining question with an LLM
   (`OPENROUTER_API_KEY` + `AUTOJOB_ANSWERS_LLM_MODEL`, falling back to
   `AUTOJOB_LLM_MODEL`) and answers it from the store
   (`data/answers.json`) **by meaning**, and **Task 10** lets it **match or
   derive**: it may copy a stored answer, or produce a short answer the stored
   entries *entail* when no stored value can be copied verbatim (a positive
   "years of experience with artificial intelligence (ai)" entry answers
   "Experience on AI? [Yes/No]" as **Yes**). Every answer must cite the stored
   key(s) it used (`source_keys`); an answer with no existing cited source, a
   derive the cited values do not entail, or a choice answer that maps to none of
   the question's options is rejected and handed to Task 5 — the model never
   invents an answer or uses outside knowledge. A derived answer is cached in
   `data/derived_answers.json` (kept separate from the human-confirmed
   `answers.json`) so the same question is instant next time. It also attaches the
   chosen resume — preferring a resume already listed on the form over uploading
   a duplicate — and advances multi-step forms. **Task 12** handles a free-text
   question about this job, employer, role, or the applicant's fit (for example
   "What attracts you to Propeller as an employer?") by answering it from the
   **current job description** and the **selected resume**, with cited evidence;
   normal/factual questions (salary, city, work authorization) still use the store
   or Task 5, and generated context answers are never written to either store. A
   **checkbox** question ("select
   all that apply") is answered as one group: its options are treated as a single
   question, and a stored answer ticks every matching box. It **stops before Submit
   application** and never clicks it.
   - **Task 11 (inside fill):** if a dynamic-form step crashes (no resume control,
     the form will not advance, a navigation button disappears, or the fill raises),
     the agent writes a failure bundle and a `BUG-NNN` entry, closes the browser,
     optionally runs the configured OpenCode repair command and its tests, then reopens the
     **same** job and re-fills it. Attempts are capped
     (`AUTOJOB_SELF_HEAL_MAX_ATTEMPTS`, default `3`); on exhaustion the evidence is
     preserved and the run stops. With no repair command configured it performs
     runtime recovery only.
   - **Task 25 (inside fill):** invalid-input recovery first tries a truthful
     number/text conversion, such as `2 years` → `2`, or `2` → `2 years` when the
     question supplies the unit. Ambiguous or constraint-violating conversions
     use the existing correction/skip flow, with metadata-only conversion outcomes.
     See [answer type conversion](docs/task25-answer-type-conversion.md).
   - **Task 20 (inside fill):** a visible invalid-input error gets one correction
     pass and one navigation retry, using truthful answers and the live field's
     constraints. A successful correction continues the same application. If no
     safe correction fits or the error persists, the agent saves the direct job
     link, error, and correction outcome in `data/invalid_input_skips.json`,
     closes/discards Easy Apply, and selects the next eligible job. These skips
     never count as submissions and their posting IDs remain excluded across
     pages/date ranges. A log-write or close failure stops safely; validation
     never invokes structural self-healing. See [Task 20 recovery](docs/task20-validation-recovery.md).
   - **Task 5 (inside fill):** when the LLM cannot choose a grounded answer for a
     required (`*`) question, the agent shows a banner in the browser window
     saying it does not know the answer,
     **pauses for you to type it into the form field on the page** (the banner has
     no input of its own), reads the value you enter, fills the field, and saves
     the question → answer mapping. Task 4.1 reuses that answer next run — and, as
     a human-confirmed answer, it always takes precedence over a derived one.
     Text is saved only after blur, Enter, or **Done**. Use **Done** after selecting
     multiple checkboxes. Skip and inactivity timeout discard unfinished answers.
     Choice
     fields (selects/radios) list their allowed options in the banner, and an
     answer that matches a visible option label is mapped to the right value.
     A dropdown's prompt ("Select an option") is never treated as your answer —
     opening the list or clicking away changes nothing — and a value recorded for
     one question is never reused as the answer to another.
     A **checkbox** question is asked **once** for the whole group and *every*
     option you tick is captured — the banner watches all of the group's options,
     so ticking any of them is saved under the group's question (and no tick you
     make is ever toggled off by the agent). Controls the form has **already filled** (e.g. LinkedIn's pre-filled *Email
     address* / *Phone country code* selects) are left as-is and never asked
     about. Click **Skip** in the banner to skip on purpose.
     Set `AUTOJOB_SESSION_ASK_HUMAN=false` to leave unknown questions unanswered
     instead of prompting. Questions you skip or leave unanswered are recorded and
     can be answered on a later run.
   - **Task 24 (inside fill):** missing required answers, including “This field is
     required” on radio groups, use the existing grounded chooser and then the same
     human banner. Recovery checks the actual controls after re-renders and retries
     Next/Review once. Each question gets one automatic attempt and one prompt per
     step, with a five-question recovery cap. Unresolved answers use Task 20's
     durable log and safe skip path. Optional questions stay untouched and recovery
     never submits. See [required-answer recovery](docs/task24-required-answer-recovery.md).
5. **await_submit** — **Tasks 8/22:** in manual mode, leaves the browser open on the
   terminal step and **waits for you to submit** the application yourself.
   In automatic mode, checks required answers, validation, and the current
   terminal control, then clicks **Submit application** once. It polls for a submission
   confirmation ("Your application was sent to X!" / "Application sent" / "Done")
   or the job's card flipping to **"Applied"**, bounded by
   `AUTOJOB_SESSION_KEEP_OPEN_TIMEOUT_SECONDS`. A modal dismissed with X, or a
   closed window, without a confirmation is **not** a submission. On a detected
   submission the post-apply dialog is closed with a safe dismiss control —
   **Not now** (or the X / **Done**) — never **Update profile** — and the job is
   recorded (title, company, resume) on the Task 8 outcome.
   Automatic mode stops for manual review if confirmation is missing; it never
   retries the click or reopens this submission through self-healing. Its timeout
   is `AUTOJOB_SESSION_AUTO_SUBMIT_TIMEOUT_SECONDS` (default: 30 seconds).
   Uncertain automatic attempts return `needs_review` and save diagnostic evidence
   under `data/debug/task22/`, with the path included in the run log.
6. **next_job** — **Task 8 (subtask 8.2):** back on the results list, re-reads the
   cards, skips the **"Applied"** ones (Task 6), paginates when a whole page is
   Applied (Task 7), and selects the first unapplied **Easy Apply** job, reading
   its description so `match` decides whether to open its form and `fill` runs
   again. Any leftover post-apply dialog ("Your application was sent..." / "Turn
   your resume into a profile") is dismissed first so it cannot cover the next
   card. **Task 16:** a job skipped for having no matching resume never had its
   Easy Apply form opened, and its title is excluded from later passes, so the
   loop never reopens it. **Task 17:** when the whole startup range is exhausted,
   the same scan falls back to the other range (Past 24 hours ⇄ Past week) and
   continues; a scan already on the fallback range stays there. Skips are uncapped by default; set
   `AUTOJOB_SESSION_MAX_SKIPPED_JOBS` to a positive number to stop after that many
   unmatched jobs.
   The loop otherwise repeats until `AUTOJOB_SESSION_MAX_JOBS`
   jobs have been submitted (default `35`; `0` = until no unapplied job remains),
   every job
   is Applied, you close the browser, or a step fails — each with a clear
   `stopped_reason`. Skips never count as applications. The session is reused
   across iterations.
7. **cleanup** — releases the shared browser session on every path. The **agent
   never closes the browser**: the Chromium window is left open so you can inspect a
   failure and keep driving it yourself. At the last step (Task 4 only **Submit
   application** remains) the run waits for you to close the window (or
   `AUTOJOB_SESSION_KEEP_OPEN_TIMEOUT_SECONDS` elapses) and leaves it open either
   way. Run `autojob --clean-profile` to force-close a leftover browser.
8. **verify** — passes only when all of the above succeeded (including a clean
   Task 8 stop reason; your submission is never a failure). **Task 16:** a run
   whose last job was skipped because no existing resume matched (or that skipped
   every job) also finishes cleanly, with the skipped count and the LLM rationale
   in the summary; an unreadable description or an LLM/match error still fails.
   Otherwise the run fails and a full-page screenshot plus the page URL are
   recorded under `data/debug/`.

The browser interaction is deterministic (browser-use's CDP actor API). The resume
match (Task 3.2) and the answer choice (Task 4.1/10) use an LLM; the LLM never drives
the browser or submits anything.
The login gate is human: your session is stored in the persistent Chromium
profile under `data/profile`, so later runs skip the wait.

**Task 9 — live status in the browser.** While a run is active, a small panel is
injected into the same LinkedIn page (bottom-left, so it never covers the Task 5 /
Task 3.1 banners in the bottom-right). It updates in place and shows only the
latest step, saying in plain language what the agent is doing at each step ("Please wait —
searching for 'software engineer' jobs…"). Whenever the **LLM** is used it is shown
with an explicit `LLM:` label and a purple heading, naming exactly what it is doing
(summarising a resume, choosing the best-matching resume, classifying a form
question) and what it decided. For a Task 10 answer it also names the stored
source and whether the answer was **matched** or **derived** (e.g. `LLM: answered
'Experience on AI? [Yes/No]' - 'Yes' (derived from 'how many years of work
experience do you have with artificial intelligence (ai)': '5')`). A Task 12
job-context answer names its source instead, e.g. `LLM: answered 'What attracts
you to Propeller as an employer?' - 'I am drawn to Propeller's mission…' (from the
job description + your resume)`. The panel is
read-only, best-effort feedback: a failed render never fails or slows a step, and
it is removed when the run ends.

**Task 11 — self-healing a broken Easy Apply step.** When a fill stops for a
structural reason, `src/tools/self_healing/` captures a screenshot, DOM excerpt,
visible page text, browser console/error lines, the current fields/buttons/resume
controls, and the exception. The bundle is written under
`data/debug/self_healing/<timestamp>-<fingerprint>/`; `known Bugs/self_healing_bugs.md`
gets a deduplicated `BUG-NNN` entry and `known Bugs/bug_log.md` is updated. The
failed browser is then closed with `session.kill()` (not just detached), and the
loop reopens the **exact page URL captured from the address bar** in a fresh
Chromium session (for example the `jobs/search-results/?currentJobId=…` page), then
clicks **Easy Apply** and re-fills the same job.
It never clicks **Submit application**.

`AUTOJOB_SELF_HEAL_REPAIR_COMMAND` is optional and opt-in. It runs after the
browser is closed, with `AUTOJOB_FAILURE_BUNDLE`, `AUTOJOB_FAILURE_REPORT`,
`AUTOJOB_FAILURE_FINGERPRINT`, `AUTOJOB_FAILURE_CATEGORY`, and `AUTOJOB_BUG_ID` in
its environment, followed by `AUTOJOB_SELF_HEAL_TEST_COMMAND` (default
`uv run pytest -q`). A failing test stops the loop instead of patching again. After
a successful repair/test the browser and fill modules are reloaded in-process;
changes to graph/node/state modules still require a normal agent restart. Without a
repair command the loop only retries the same job within the attempt cap.

The shipped command points the repair hook at the **OpenCode agent**:

```env
AUTOJOB_SELF_HEAL_REPAIR_COMMAND=uv run python scripts/self_heal_repair.py
AUTOJOB_SELF_HEAL_TEST_COMMAND=uv run pytest -q
```

`scripts/self_heal_repair.py` reads the bundle, builds a prompt from the AGENTS.md
self-healing loop **and the `incremental-implementation` skill** (whose `SKILL.md` is
attached to the session), and runs `opencode run --auto --file <report> "<prompt>"` in
the project root, so the agent diagnoses the root cause, lands the fix in thin
testable slices, adds a regression test, and updates the bug log before the loop
reopens the job. Its output
**streams live** to the run console (prefixed `self-heal:`) and is also saved to the
bundle's `repair.log`/`tests.log`; the session is titled `self-heal <BUG-ID>` so it can
be watched in the OpenCode TUI. The repair session uses
`AUTOJOB_SELF_HEAL_REPAIR_MODEL` (default `deepseek/deepseek-v4.1-flash-1017`,
mapped to OpenCode's `openrouter/deepseek/deepseek-v4.1-flash-1017`) and never
reuses `AUTOJOB_LLM_MODEL`; set `..._AGENT` to choose the OpenCode agent, or
`AUTOJOB_SELF_HEAL_OPENCODE` when the CLI is not on `PATH`. A
missing/unavailable repair model fails closed: the error stays in `repair.log`,
the bug remains 🔴 Open, and the bounded loop stops without retrying on the
general model.

**Task 12 — answer job-specific questions from the job and your resume.** At the
start of every fill (and every self-healed retry), the agent builds a fresh
**per-job context**: the current job description (title, company, location, body,
URL) plus the resume Task 3 selected, its extracted text (read-only, capped to a
safe prompt size), and its stored Task 3.2 profile. No previous job's context is
ever reused. For a free-text question about this job/employer/role or your fit for
it, the LLM answers from those two sources in a short first-person reply, cites
verbatim `evidence`, and returns `job_specific`; the answer is only filled when it
passes grounding checks:

- non-empty, at most 1,200 characters, and not a placeholder or a restatement of
  the question;
- every claimed source (`resume`, `job_description`, or both) has at least one
  evidence snippet that actually appears in it;
- every number in the answer appears in the resume or job description;
- a question about the employer/company gets the company name in the answer;
- choice controls (radio/select/checkbox) never receive prose.

An exact human-confirmed `data/answers.json` entry always wins. A likely
job-specific question does **not** reuse a similar-but-stale store answer: if the
context cannot ground it, it goes to **Task 5**. Normal/factual questions (salary,
city, work authorization, notice period, years of experience, …) skip the context
path entirely and keep the existing Task 4.1/10 store behavior or Task 5.
Generated context answers live only in the run state/log (and Task 9's `LLM:`
line); they are **never** written to `answers.json` or `derived_answers.json` and
are recomputed for each job. The application is never submitted.

## Requirements

- Python 3.11 or 3.12
- [uv](https://docs.astral.sh/uv/)
- [OpenCode](https://opencode.ai/) CLI — only for the opt-in self-healing repair hook
  (`AUTOJOB_SELF_HEAL_REPAIR_COMMAND`); the wrapper runs `opencode run` to fix the code.

## Setup

```bash
uv sync                        # core (no browser); includes pypdf for resumes
cp .env.example .env           # optional; defaults are safe
```

Put one or more resumes in `resumes/` (supported: `.pdf`, `.docx`, `.txt`, `.md`).
To add a resume later, put it in `resumes/new/`; Task 3.2 describes it and moves
it into `resumes/` on the next matching run (or run
`uv run autojob --describe-new-resumes` to do it immediately, without a browser).

Task 23 lets Task 3 and Task 10 use different LLM models. Set their optional
overrides independently; an unset or blank override uses the general model:

```bash
OPENROUTER_API_KEY=sk-or-...                                     # shared credential
AUTOJOB_LLM_MODEL=xiaomi/mimo-v2.6-pro                           # general-purpose
AUTOJOB_RESUME_LLM_MODEL=                                      # Task 3/15 override
AUTOJOB_ANSWERS_LLM_MODEL=                                     # Task 4.1/10 override
AUTOJOB_SELF_HEAL_REPAIR_MODEL=deepseek/deepseek-v4.1-flash-1017 # repair agent
```

Set `AUTOJOB_RESUME_LLM_MODEL` to the model ID for resume descriptions and
best-resume selection, including new resumes processed by Task 15. Set
`AUTOJOB_ANSWERS_LLM_MODEL` to a different model ID for matching and deriving
answers from the stored knowledge. Both reuse the existing key, endpoint,
timeouts, retries, and request options. An override works without a general
model; it never falls back to the other task's override.

Task 12's job-context reasoning keeps `AUTOJOB_LLM_MODEL`, even when it wraps
the Task 10 store chooser. With neither override set, all three purposes use
the general model as before. The self-healing model
(DeepSeek V4.1 Flash 1017) is used only by the Task 11 repair agent; it defaults
to DeepSeek even when the general model is MiMo. Changing a task override never
changes another task, the general model, or self-healing. Failed requests retain
their existing error/unknown-answer handling without switching models. Use bare
provider model IDs for general/resume/answer calls; the repair wrapper maps the
default bare DeepSeek id to OpenCode's
`openrouter/...` form, while an explicit override is passed to OpenCode verbatim
(use a `provider/model` id to select another provider). The startup log names
the general, `task3`, `task10`, and self-healing models for every run.

To verify routing in LinkedIn, configure two distinct task models and run
`uv run python -m scripts.verify_task23_linkedin --walk`. It launches the saved
browser profile, matches a resume, and walks the dynamic Easy Apply form without
submitting. `--resume-model` and `--answers-model` can temporarily override the
models for this check; `--job-id` selects a specific posting, and `--cdp-url`
attaches to an already running dedicated browser. Evidence under
`data/debug/task23/` records request/response model IDs, HTTP status, form results,
and screenshots without credentials. Unsupported required answers retain the
normal Task 5 prompt and Task 20 validation handling. The shared label reader
recognizes visible CSS-generated asterisks as well as text asterisks, keeping
these required questions eligible while unstarred questions remain untouched.

Any OpenAI-compatible endpoint works via `AUTOJOB_LLM_BASE_URL`. Without a key
and a resolved model for the purpose, its LLM calls are unavailable. Unknown
form questions are handed to Task 5 (ask the human); resume calls report a
configuration error.

Task 3.2's structured calls (resume descriptions and the resume match) ask for
JSON and, on OpenRouter, skip the model's hidden reasoning by default
(`AUTOJOB_LLM_DISABLE_REASONING=true`). That keeps a warm resume match to a
couple of seconds and avoids an empty reply when reasoning fills the output
budget. Set it to `false` if your endpoint needs the model's reasoning. The
match reply includes a rating for every candidate as well as the single choice;
if the choice is only `partial` but another candidate is rated `strong`, the
strong candidate is used instead of skipping the job. The description store is
versioned, so changing the profile prompt re-describes the pool on the next run.

To answer form questions automatically, add them to the answer store
`data/answers.json`. Task 4.1/10's LLM reads it and answers each question —
matching by meaning, not exact wording, and **deriving** an answer the stored
entries entail when no stored value can be copied verbatim; Task 5 also writes to
this file when it asks you a new question in the browser, so answers persist
across runs. Every auto-answer is grounded: the model must copy a stored value or
cite the stored key(s) it derived from, so it never invents one. Derived answers
are cached in `data/derived_answers.json` (a separate file, so `answers.json`
stays human-confirmed).
**Task 12** answers a free-text question about the current job/employer/role from
the job description and the selected resume instead; those answers are generated
per job, validated against cited evidence, and never stored in either file.
For example:

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

# Real run - asks for the date range and manual/automatic submission mode, opens
# Chromium, waits for login, searches, opens Easy Apply, reads the job, picks a
# resume, and fills the form. Manual submission is the default.
uv run autojob --no-dry-run
uv run autojob --no-dry-run --date-range week
uv run autojob --no-dry-run --query "software engineer" --resumes-dir ./resumes

# Select submission mode explicitly and skip its startup question.
uv run autojob --no-dry-run --submission-mode auto
uv run autojob --no-dry-run --submission-mode manual

# Task 15: describe resumes in resumes/new/, then move them into resumes/
uv run autojob --describe-new-resumes
```

`--date-range` accepts `24h`/`past_24_hours` or `week`/`past_week`. When it is
omitted, an interactive terminal asks which range to scan first (default: **Past
24 hours**); a non-interactive run (tests, piped output, LangGraph Studio) keeps
that default. When the chosen range is exhausted, the agent falls back to the
other range.

Task 22 asks who should submit each application before the browser starts.
Press Enter for **manual**, or select **automatic** for the whole run. An explicit
`--submission-mode manual|auto` skips this question. Non-interactive runs, EOF,
and interrupted prompts default to manual. Maintenance modes never prompt.
See [submission modes and verification](docs/task22-submission.md).

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
  date_range.py      Task 17: normalized Past 24 hours / Past week helpers
  date_range_choice.py  Task 17: startup prompt for the primary range
  state/            Shared state, split by concern; existing src.state imports work
    __init__.py     Public model/state re-exports
    outcomes.py     Job, resume, context, and field models
    forms.py        Task 4/5 form and human-answer outcomes
    core.py         Graph state and aggregate outcomes
  state_loop.py      Task 8/16 loop + skip outcome models (re-exported by state)
  graph.py           Graph assembly (START -> ingest -> browse -> match -> fill -> await_submit -> next_job -> ... -> cleanup -> verify -> END)
  nodes/
    ingest.py        Validate the LinkedIn URL and search query
    browse.py        Tasks 1-3 browser work (login, search, Easy Apply, description)
    match.py         Task 3: describe the pool + LLM-pick the best resume (offline)
    fill.py          Task 4 + Task 11: fill the form, recover a structural crash
    apply_loop.py    Task 8: wait for the human's submit (await_submit) + open the next job (next_job)
    cleanup.py       Close the shared browser session (or leave it open at the last step)
    verify.py        Confirm every task's acceptance criteria
  tools/
    browser/         browser-use wrapper (opt-in), with the existing public imports
      __init__.py    shared API and lazy Task 1–5 exports
      runs.py        live run registry, final human review, and session detachment
      orchestration.py  start_tasks / fill_application / run_agent / run_full_agent
      profiles.py    dedicated Chromium sessions and profile recovery
      primitives.py  shared CDP helpers and failure screenshots
      queries.py     shared DOM query literals
      task_exports.py  lazy compatibility exports
    linkedin.py      Pure LinkedIn URL/text helpers
    linkedin_search/              Task 1: log in, search jobs, apply the filters
      __init__.py                 public API (re-exports the submodules below)
      common.py                   one-control-at-a-time click settle
      search_box.py               login gate, jobs search bar, results wait
      easy_apply_filter.py        find/select/verify the Easy Apply filter
      ai_search.py                optional "Try AI job search" detour
      orchestrator.py             Task 1 step sequence (filters + failure outcome)
    linkedin_date_posted/          Task 13/17: Date posted ranges + URL helpers
      __init__.py                  public API (re-exports the submodules below)
      labels.py                    range labels, f_TPR values, pure helpers
      queries.py                   pill/options/Show-results discovery scripts
      selection.py                 select Past 24 hours / Past week, verify
      urls.py                      f_TPR URL helpers + page-offset reset
    linkedin_date_range_fallback.py  Task 17: switch ranges, keep Easy Apply
    linkedin_results_scan.py         Tasks 7/17: page walk + two-way range fallback
    linkedin_job_selection.py      Task 2: select a job and read its description
    linkedin_job_card.py           Task 2: resolve a card + verify the details pane
    linkedin_job_apply_button.py   Task 2: the details pane's job, apply button, modal
    linkedin_easy_apply_open.py    Task 2b: click Easy Apply only after a resume match
    linkedin_skip_applied.py       Task 6: skip cards already marked "Applied"
    linkedin_pagination.py         Task 7: when a page is all Applied, go to the next page
    linkedin_apply_loop.py         Task 8: detect the human's submit, open the next job
    linkedin_resume_gate.py        Task 16: strict match gate + safe form-close fallback
    linkedin_status_overlay/      Task 9: the on-page status panel + input lock
      __init__.py                   public API (re-exports the submodules below)
      panel_js.py                   the status panel's DOM scripts
      status_reporter.py            CLI + panel reporter, emit_step/emit_llm
      interaction_lock.py           BUG-067 input lock + human-turn unlock
    linkedin_best_matching_resume/  Task 3: read the job description + LLM match
      __init__.py                   public API (re-exports the submodules below)
      description_reader.py         deterministic job read (title scoped to the pane)
      resume_text.py                resume discovery + text extraction (read-only)
      resume_prompt.py              Task 3.1 browser banner (upload / skip)
      selection.py                  Task 3 flow: describe pool, LLM pick, fallback
    resume_descriptions/            Task 3.2: LLM resume profiles + the LLM pick
      __init__.py                   public API (re-exports the submodules below)
      models.py                     ResumeDescription / ResumeMatch / error type
      messages.py                   prompts + tolerant balanced-JSON parsing
      experience_policy.py          Task 19: experience-neutral match view
      store.py                      description store + parallel ensure_descriptions
      client.py                     JSON-mode LLM calls (reasoning off, retry)
    linkedin_easy_apply_fill/      Task 4: fill the Easy Apply form, attach the resume
      __init__.py                  Task 4 public API (re-exports the submodules below)
      form_queries/                DOM queries + readers for the form, resume controls, buttons
        __init__.py                re-exports the query scripts and readers
        scripts.py                 injected JS query scripts + findApplyRoot injection
        readers.py                 async readers over the scripts (read_form, read_resume_info, ...)
      required_only.py             Drop optional (no `*`) questions before filling
      question_labels.py           Resolve each question's own visible label/group heading
      field_filling.py             Fill one step's required fields (LLM / Task 5 answers)
      checkbox_groups.py           Answer a checkbox (multi-select) question as one group
      resume_attachment.py         Attach the Task 3 resume (listed option or CDP upload)
      form_walk/                   Walk dynamic steps; core and rendering readiness
      step_state.py                Stable step identity and required-question notes
    llm_answers.py   Task 4.1: LLM classifies a question and picks the stored answer
    llm_answer_reasoning.py  Task 10: LLM matches *or derives* an answer, with grounding
    derived_answers.py  Task 10.3: cache of answers the LLM derived from the store
    job_context.py   Task 12: build/cap the per-job job description + selected resume
    job_context_answers/  Task 12: job-specific prefilter, prompt, grounding, routing
      filters.py      job-specific/factual free-text classification
      prompt.py       job-context prompt + tolerant JSON parse
      validation.py   evidence/number/placeholder/company grounding
      chooser.py      the LLM call + context-aware AnswerChooser routing
      presentation.py Task 9 status line + FormField provenance
    linkedin_ask_human/  Task 5: banner, answer watcher/reader, wait flow, answer store
    matching.py      Pure keyword helpers (skills, titles, seniority) for 3.1 profiles
    answers.py       Question -> answer store (read by Task 4.1/10, written by Task 5)
    resume_library.py  Task 3.1: job profiles -> human-provided resumes
    resume_intake.py   Task 15: describe new resumes, then move them into the pool
    forms.py         Pure Easy Apply form helpers (resume match, next/submit)
    self_healing/    Task 11: failure fingerprint, evidence capture, bug log, bounded
                     close/reopen/resume loop, optional OpenCode repair+test hook
  main.py            CLI entry point
scripts/             Task 11: self_heal_repair.py hands a failure bundle to OpenCode
resumes/             Candidate resumes (.pdf, .docx, .txt, .md)
resumes/new/         Task 15: intake resumes, described then moved into resumes/
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

- **"another browser is already using the AutoJobApply profile …"** — the agent
  never closes the browser, so the window from a previous run is still holding
  `data/profile`. Close that window (or run `uv run autojob --clean-profile`) before
  starting the next run.

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
- Task 4 answers via the LLM (Task 4.1/10), which only uses **stored** answers — it
  may copy one or **derive** one the stored entries entail, always citing the
  stored key(s) it used, so it can never invent an answer — attaches the chosen
  resume, and stops at the review step. **Task 22** then follows the startup
  submission choice; manual mode is the default. **Task 12** adds a second grounded source
  only for job-specific free-text
  questions: the current job description and the selected resume. Its answer must
  cite evidence that actually exists in every claimed source, is length-bounded,
  and is rejected (Task 5 asks you) when unsupported. Choice controls never
  receive prose; generated context answers are never written to `answers.json` or
  `derived_answers.json`.
- Task 5 never guesses: when the LLM cannot choose a grounded answer, the run
  pauses on a browser banner and waits for you to type the answer into the form
  field. Answers are stored in `data/answers.json` (no credentials) and reused by
  Task 4.1/10; a human-confirmed answer always takes precedence over a derived one.
  The derived answers the LLM produced are cached separately in
  `data/derived_answers.json` (never written into `answers.json`).
- Unknown questions that you skip or leave unanswered are recorded rather than
  guessed. A checkbox (multi-select) question is answered as one group and keeps
  every option you tick; the agent never unticks a box you selected.
- Task 3 only **reads** existing resumes — it never renames, moves, or edits them.
  Task 15 is the one exception for the **intake folder**: after a resume in
  `resumes/new/` is described, it is moved into `resumes/` without changing its
  bytes or overwriting an existing file. The description entry follows the file.
- **Task 16 (default)** applies only when an existing resume is a **strong** match.
  Matching happens **before** Easy Apply, so an unmatched job is skipped without
  ever clicking the form open. The agent never fills or submits an unmatched
  application, never asks for a resume in strict mode, and never reuses the
  remembered-resume library for a job the LLM did not match. The skip is recorded
  in the run summary and the `task16` state, and the skipped title is not reopened
  this run. **Task 19:** the matcher ignores the job's years-of-experience
  requirement; a resume with fewer years than requested is still eligible and can
  be rated `strong`, while genuine skill/domain gaps still cause a skip.
- **Task 17 (default)** asks at startup whether to scan **Past 24 hours** or
  **Past week** first. When that range is exhausted it falls back once to the
  other range (24 hours ⇄ past week). It resets the results to page 1, preserves
  **Easy Apply**, carries over applied/skipped job keys, and never selects **Past
  month**. The requested and used ranges are reported in the `task2` outcome and
  CLI summary.
- Task 11 records a structural Easy Apply failure **before** recovery, never
  submits during recovery, and stops after the configured attempt cap instead of
  retrying or patching forever. If no repair command is set, it only reopens the
  same job with the current code.
  Task 3.2 stores LLM-written profiles in `data/resume_descriptions.json`. Task 3.1
  may **add** a resume you upload when nothing matches (never overwriting an
  existing file) and remembers its job profile in `data/resume_library.json`
  (profiles and paths only, no credentials) so similar jobs reuse it.
- On failure the page URL and a screenshot are saved for debugging.
- The Chromium profile under `data/profile` persists logins and is gitignored.
