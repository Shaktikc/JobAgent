# Task 16 — Apply only when an existing resume matches the job; skip unmatched jobs

**Status:** ✅ Done

**Goal:** Add a **strict resume-gated apply** mode. When it is enabled (the default),
the agent applies to a job **only** when the LLM (Task 3.2) chooses one of the
resumes already present in `resumes/` as a genuine match for that job. If no
existing resume matches, the job is **skipped**: close the already-open Easy Apply
form, record the skip with the LLM's rationale, open the next unapplied job
(Tasks 6-7), and continue the loop. The agent must **never** ask the human to
upload a resume for an unmatched job, never reuse a remembered/unmatched resume as
a bypass, and never fill or submit an application for a job without a matching
resume. The application is **never** submitted by this task.

**Preconditions**
- Tasks 1-8 are complete: the graph opens a job's Easy Apply form, matches a
  resume, fills the form, waits for the human to submit, and opens the next job.
- Task 3.2 is implemented (`src/tools/resume_descriptions/`): every resume has an
  LLM-written description and the LLM chooses the best match or **none**.
- Task 3.1's fallbacks exist today: reuse a resume remembered for a similar job,
  or ask the human to upload one in the browser.
- `settings.llm` is configured. Strict mode **fails loudly** (no skip, no guess)
  when the LLM is unconfigured or the match call fails, because the agent cannot
  decide whether a resume matches.
- The existing applied-job skip (Task 6) and pagination (Task 7) remain in force;
  skipping an unmatched job is a separate, additional reason to move on.

**Inputs**
- The open job's description (Task 3).
- The resume pool (`resumes/`) and each resume's stored LLM description
  (Task 3.2). "Already provided" means the files present in the pool when the job
  is matched; strict mode never adds a resume during a run.
- The LLM match reply: chosen candidate (or **none**), match quality, and
  rationale.
- `.env` / process environment:
  - `AUTOJOB_SESSION_REQUIRE_RESUME_MATCH` — strict mode; default `true`.
  - `AUTOJOB_SESSION_MAX_SKIPPED_JOBS` — safety cap on skips per run; default
    `100`, `0` = no cap. A skip is **not** an application and does not count
    toward `max_jobs_per_run` (Task 8).
- The results-list job identity used to avoid re-opening a skipped job.

**Steps**
1. **Add the strict-mode setting.**
   - Add `SessionSettings.require_resume_match: bool = True` (env
     `AUTOJOB_SESSION_REQUIRE_RESUME_MATCH`) and
     `SessionSettings.max_skipped_jobs_per_run: int = 100, ge=0` (env
     `AUTOJOB_SESSION_MAX_SKIPPED_JOBS`).
   - Document both in `.env.example` and `README.md` next to the existing Task 6
     `AUTOJOB_SESSION_SKIP_APPLIED` setting. Setting
     `AUTOJOB_SESSION_REQUIRE_RESUME_MATCH=false` restores today's Task 3.1
     fallbacks (remembered resume / ask the human) exactly.
2. **Make the match quality explicit (LLM-only, no deterministic scorer).**
   - Extend `ResumeMatch` (`src/tools/resume_descriptions/models.py`) with
     `fit: str = ""`, normalised to `"strong"`, `"partial"`, or `"none"`.
   - Update the match prompt (`messages.py`) to require
     `{"choice": "<id or none>", "fit": "<strong|partial|none>", "rationale":
     "<short reason>"}` and to define the bar: **strong** only when the resume
     genuinely satisfies the job's core requirements (skills/technologies, title,
     seniority, domain); **partial** for a transferable but incomplete fit;
     **none** when no candidate is a reasonable fit. Keep the rule that the model
     may choose only a provided id and never invents a file.
   - Parse and normalise `fit` forgivingly; an unknown/missing value becomes `""`.
     The match decision remains an LLM decision — do **not** add keyword scoring.
3. **Gate the match in strict mode.**
   - `src/tools/linkedin_best_matching_resume/selection.py`:
     `ensure_resume(..., allow_fallback: bool | None = None)` reads
     `settings.session.require_resume_match` when `allow_fallback` is `None`.
   - When strict and the LLM answers **none**, a chosen resume has `fit` other
     than `"strong"`, or `fit` is missing: set `Task3Outcome.no_match = True`,
     record the rationale/fit, and **return immediately**. Do not look in the
     remembered-resume library, do not call `ask_human_for_resume`, do not store
     or upload anything. A missing `fit` fails closed (skip, never apply).
   - A `"strong"` selection is used exactly as today: record the path, fit, and
     rationale, and hand it to Task 4 to attach/upload. The resume files are never
     modified.
   - `Task3Outcome` gains `fit: str = ""` so the decision is auditable.
   - When `allow_fallback` is true (legacy mode), behaviour is unchanged: a
     non-strong/no-match result goes through the remembered-resume reuse and the
     human-upload fallback as today.
4. **Skip instead of failing in the graph.**
   - `src/nodes/match.py`: a strict no-match is a **clean skip**, not an error.
     Return `status="skipped"` and the updated `task16` outcome; do not append to
     `errors` and do not set `task4`. A missing/unreadable job description is
     still a hard failure, and an LLM/matching error still fails the run.
   - `src/graph.py`: route `match → next_job` when `task3.no_match` and strict
     mode is on with no errors; keep `match → cleanup` for errors and
     `match → fill` for a strong match. Make sure the task-level self-heal guard
     does not treat a deliberate skip as a crash (no error is returned).
5. **Close the open Easy Apply form safely before moving on.**
   - Task 2 already opened the form before Task 3 matches, so a skip leaves the
     modal covering the results list. Add a bounded
     `close_easy_apply_form(page)` helper (new module, see Notes) that clicks only
     a dismiss control inside the Easy Apply modal (`X`/`Close`/`Dismiss`; a
     `Discard` control is acceptable only for this unsubmitted draft) and waits
     for the modal to disappear. **Never** click **Submit application** or any
     apply/update-profile control.
   - Call it at the start of `open_next_job()` (before re-reading cards) so a
     skipped job never blocks the next click. If the modal cannot be closed after
     the bounded attempts, stop the loop cleanly with a clear note instead of
     retrying blindly.
   - Best effort only: a modal that is already gone is a no-op.
6. **Accumulate skipped jobs and never re-open them.**
   - Record every skip in a new `Task16Outcome`
     (`src/state.py`): `enabled`, `jobs_skipped`, and
     `skipped: list[SkippedJobRecord]` with the job title, company, index,
     `fit`, and LLM rationale.
   - Add an append-only `skipped_titles` channel to `ApplyState` and have
     `match` append the skipped job's normalised title. Pass the accumulated list
     from `src/nodes/apply_loop.next_job` into
     `src/tools/linkedin_apply_loop.open_next_job(..., skip_titles=...)` and turn
     them into `skip_keys` (existing `_job_key`) alongside the current
     `skip_title`. This prevents the loop from reopening every previously skipped
     job on each pass, not just the most recent one.
   - Keep `skip_title` working for the existing submit-and-repeat path, so older
     callers/tests do not change.
   - `Task8Outcome` may expose `jobs_skipped` for the run summary; a skipped job
     must never increment `jobs_applied` and is not recorded as `"submitted"`.
7. **Remember and report the skip.**
   - Log one line per skip, for example
     `skip: "Data Analyst" - no existing resume is a strong match (fit=partial;
     rationale=...)`, and show a status-overlay step:
     "Skipping '<title>' - no matching resume; opening the next job."
   - Update the CLI run summary (`src/main.py`) and `verify` so a run can end
     cleanly when jobs were skipped:
     - if at least one job was submitted/filled, the run passes even when the last
       opened job was skipped (judge from `task8`/`task16`, not only the last
       job's `task3`/`task4`);
     - a run that skipped every job because none matched still ends as a **clean**
       `done` with "no job matched an existing resume", not a failure;
     - errors, an unreadable description, or an LLM failure remain failures.
   - Apply the skip cap (`max_skipped_jobs_per_run`): when reached, stop the loop
     with `Task8Outcome.stopped_reason = "reached the skipped-jobs cap (N)"`.
     When no unapplied job remains, keep Task 6/7's existing stop reason.
8. **Run the tests.**
   - Focused unit tests first, then the full suite (`uv run pytest -q`) and lint.
   - Do not weaken or delete Task 3.1's fallback tests: add `allow_fallback=True`
     cases so legacy mode keeps its coverage, and new strict-mode cases.

**Acceptance criteria**
- With strict mode on (default), a job is applied to **only** when the LLM returns
  a chosen resume with `fit="strong"`; that resume is attached by Task 4 as today.
- When the LLM answers **none**, `fit` is `"partial"`/`"none"`/missing, or the
  resume pool is empty, the job is **skipped**: no human prompt, no
  remembered-resume reuse, no upload, no fill.
- Every skip is recorded with the job title/company/index, `fit`, and the LLM
  rationale in `Task16Outcome` and the run log/status overlay.
- The open Easy Apply form is closed with a safe dismiss control and the next
  unapplied job is opened; the agent never clicks **Submit application**.
- Previously skipped jobs are not re-opened on later passes of the same run
  (`skipped_titles` is passed into the Task 6/7 selection).
- The loop stops cleanly when no unapplied job remains or the skip cap is reached;
  `stopped_reason` is recorded. A run that only skipped jobs is not reported as a
  crash.
- `AUTOJOB_SESSION_REQUIRE_RESUME_MATCH=false` restores the Task 3.1 fallbacks
  unchanged (remembered resume, then ask the human).
- An unreadable job description, an unconfigured LLM, or a failed match call still
  fails the run — strict mode never guesses and never silently skips those.
- Unit tests, lint, and the required live-browser check pass; the live check
  proves a matching job proceeds and an unmatched job is skipped without any
  prompt/fill/submit.
- Never click **Submit application**; submission remains a manual human step.

**Notes**
- **Order stays as-is.** Task 2 opens the Easy Apply form before Task 3 reads the
  description and matches, so a skip must close that form. Do not move matching
  before Easy Apply in this task; that is a larger restructure and would change
  Tasks 2-4. Record that option as a future improvement instead.
- **LLM-only decision.** The strict gate uses the LLM's `fit`; do not add a
  deterministic keyword/score fallback. If the LLM is unavailable or its reply is
  unusable, fail the run rather than skip-scanning every job.
- **Fail closed on missing fit.** A reply without `fit` is not a strong match;
  skipping is safer than applying on an ambiguous answer. The prompt must ask for
  `fit` explicitly so this is rare.
- **"Already provided" = the existing pool.** Strict mode never asks for or stores
  a new resume. The remembered-resume library (`data/resume_library.json`) is a
  Task 3.1 fallback and must not be consulted in strict mode.
- **File-size limit (required).** Put the new gate/skip behaviour in a new module
  (suggested `src/tools/linkedin_resume_gate.py`; split into a
  `src/tools/linkedin_resume_gate/` package with a thin `__init__.py` if it would
  cross 415 lines). No approval is needed for the file/folder name. Keep the
  existing modules below the limit while editing them.
- **Interrelated updates:** `src/configuration.py`, `.env.example`, `README.md`,
  `src/state.py`, `src/tools/resume_descriptions/{models,messages,client}.py`,
  `src/tools/linkedin_best_matching_resume/selection.py`, `src/nodes/match.py`,
  `src/nodes/apply_loop.py`, `src/tools/linkedin_apply_loop.py`, `src/graph.py`,
  `src/nodes/verify.py`, `src/main.py`, and their tests must change together.
  Document the new gate in `README.md`; do **not** edit the completed Task 3 / 6 /
  8 files beyond their status lines (the task-file rule in `AGENTS.md`).
- **Tests:** add `tests/unit/test_task16_resume_gate.py` covering:
  - strict + LLM `none` → no fallback, no human ask, `no_match=True`;
  - strict + `fit="partial"`/`fit=""` → skip;
  - strict + `fit="strong"` → selected, no skip;
  - legacy (`allow_fallback=True`) keeps remembered-resume and human-upload paths;
  - `match` returns a clean skip (no `errors`), and the graph routes it to
    `next_job`, never `fill`;
  - `open_next_job`/`next_job` pass all accumulated skipped titles and do not
    reopen them;
  - `close_easy_apply_form` clicks only a dismiss control (never submit) and
    handles an already-closed modal;
  - `verify` passes for an all-skipped strict run and still fails on errors.
  Add/extend a live-browser test (LinkedIn-shaped fixture and the real-site
  check) that skips an unmatched job, closes the form, and opens the next job.
- **Live verification required:** run the real flow and confirm in the browser
  that (a) a job with a clearly matching resume proceeds to Task 4, (b) a job with
  no matching resume is skipped with the status message, no human resume prompt,
  no fill, and (c) the next unapplied job opens. Stop before any submit click and
  leave no stale browser session or profile lock.
- **Bug log:** if implementation exposes a new bug, add
  `known Bugs/task_16_bugs.md` and its row in `known Bugs/bug_log.md` with the
  symptom, root cause, fix, status, and evidence, as required by `AGENTS.md`.
- **Self-healing:** a changed/missing dismiss control or a modal that will not
  close is a new live failure — record it, close the browser cleanly, fix and test
  it, then resume the same job from the failing step (max 2-3 attempts).
- Never click **Submit application**; submission remains a manual human step.
